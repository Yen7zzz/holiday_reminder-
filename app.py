import os
import datetime
import pytz
import json
import re
import sqlite3
import schedule
import time
import threading
from threading import Lock
import google.generativeai as genai
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from flask import Flask, request, abort

app = Flask(__name__)

# 設定台灣時區
TAIWAN_TZ = pytz.timezone('Asia/Taipei')

# Line Bot 設定
CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN',
'KRk+bAgSSozHdXGPpcFYLSYMk+4T27W/OTDDJmECpMT4uKQgQDGkLGl5+IRVURdrQ7RHLF1vUqnQU542ZFBWZJZapRi/zg0iuJJeAGM7kXIhFJqHAeKv88+yqHayFXa140YGdC2Va1wahK9QNfV8uwdB04t89/1O/w1cDnyilFU=')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET', 'b7f5d7b95923fbc5f494619885a68a04')
YOUR_USER_ID = os.environ.get('YOUR_USER_ID', 'Ueeef67149e409ffe30e60328a379e5a0')

# Google AI 設定
GOOGLE_AI_API_KEY = os.environ.get('GOOGLE_AI_API_KEY', 'AIzaSyCYACeBwSOLRligY1J1brn6dxdkID0SLfU')
if GOOGLE_AI_API_KEY:
    genai.configure(api_key=GOOGLE_AI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

# Line Bot API 設定
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 資料庫鎖
db_lock = Lock()

# 重要節日（AI 會參考這個資料）
IMPORTANT_DATES = {
    "七夕": "2025-08-29",
    "老婆生日": "1998-02-26",
    "哥哥生日": "1996-03-05",
    "媽媽生日": "1964-04-21",
    "爸爸生日": "1963-12-21",
    "結婚紀念日": "2025-01-16",
    "情人節": "2025-02-14",
    "聖誕節": "2025-12-25",
    "蝦皮慶典": "2025-09-09",
}

# ========== 新增：節日提醒功能 ==========
# 用來記錄已發送的提醒，避免重複發送
sent_reminders = set()

def get_taiwan_now():
    """取得台灣當前時間"""
    return datetime.datetime.now(TAIWAN_TZ)

def get_taiwan_today():
    """取得台灣今天的日期"""
    return get_taiwan_now().date()

def calculate_days_until(target_date_str):
    """計算距離目標日期還有幾天（使用台灣時間）"""
    try:
        target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
        current_year = get_taiwan_today().year
        current_date = get_taiwan_today()

        # 如果是年度循環的節日（生日、紀念日等）
        if any(keyword in target_date_str for keyword in ["生日", "紀念日", "情人節", "七夕", "聖誕節"]):
            target_date = target_date.replace(year=current_year)
            if target_date < current_date:
                target_date = target_date.replace(year=current_year + 1)

        days_until = (target_date - current_date).days
        return days_until, target_date
    except ValueError:
        return None, None

def send_reminder_message(holiday_name, days_until, target_date):
    """發送提醒訊息"""
    # 建立唯一的提醒 ID，避免同一天重複發送
    reminder_id = f"{holiday_name}_{days_until}_{get_taiwan_today()}"

    if reminder_id in sent_reminders:
        print(f"今天已發送過提醒：{holiday_name} - {days_until}天")
        return

    if days_until == 7:
        message = f"🔔 提醒：{holiday_name} ({target_date.strftime('%m月%d日')}) 還有7天！\n現在開始準備禮物或安排活動吧～"
    elif days_until == 5:
        message = f"⏰ 提醒：{holiday_name} ({target_date.strftime('%m月%d日')}) 還有5天！\n別忘了預訂餐廳或準備驚喜哦～"
    elif days_until == 3:
        message = f"🚨 重要提醒：{holiday_name} ({target_date.strftime('%m月%d日')}) 還有3天！\n記得買花買禮物！"
    elif days_until == 1:
        message = f"🎁 最後提醒：{holiday_name} 就是明天 ({target_date.strftime('%m月%d日')})！\n今晚就要準備好一切了！"
    elif days_until == 0:
        message = f"💕 今天就是 {holiday_name} 了！\n祝您和老婆有個美好的一天～"
    else:
        return

    try:
        line_bot_api.push_message(YOUR_USER_ID, TextSendMessage(text=message))
        sent_reminders.add(reminder_id)
        print(f"提醒訊息已發送：{holiday_name} - {days_until}天 (台灣時間: {get_taiwan_now()})")
    except Exception as e:
        print(f"發送訊息失敗：{e}")

def check_all_holidays():
    """檢查所有節日並發送提醒"""
    taiwan_time = get_taiwan_now()
    print(f"正在檢查節日提醒... 台灣時間: {taiwan_time}")

    for holiday_name, date_str in IMPORTANT_DATES.items():
        days_until, target_date = calculate_days_until(date_str)

        if days_until is not None:
            print(f"{holiday_name}: 還有 {days_until} 天")
            if days_until in [7, 5, 3, 1, 0]:
                send_reminder_message(holiday_name, days_until, target_date)

def clear_old_reminders():
    """清除舊的提醒記錄（避免記憶體無限增長）"""
    today_str = str(get_taiwan_today())
    global sent_reminders
    sent_reminders = {r for r in sent_reminders if today_str in r}

def list_all_holidays():
    """列出所有節日"""
    if not IMPORTANT_DATES:
        return "目前沒有設定任何重要節日"

    taiwan_time = get_taiwan_now()
    message = f"📅 已設定的重要節日 (台灣時間: {taiwan_time.strftime('%Y-%m-%d %H:%M')})：\n\n"
    for holiday_name, date_str in IMPORTANT_DATES.items():
        days_until, target_date = calculate_days_until(date_str)
        if days_until is not None:
            message += f"• {holiday_name}：{target_date.strftime('%Y年%m月%d日')} (還有{days_until}天)\n"

    return message
# ========== 節日提醒功能結束 ==========

def init_database():
    """初始化資料庫"""
    try:
        with db_lock:
            conn = sqlite3.connect('life_assistant.db', timeout=30)
            cursor = conn.cursor()

            # 記帳記錄表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT,
                    type TEXT NOT NULL DEFAULT 'expense',
                    created_at TEXT NOT NULL
                )
            ''')

            # AI 對話記錄表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    ai_response TEXT NOT NULL,
                    action_taken TEXT,
                    created_at TEXT NOT NULL
                )
            ''')

            # 創建索引提升查詢效率
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_date 
                ON expenses(user_id, date)
            ''')

            conn.commit()
            conn.close()
            print("✅ 資料庫初始化成功")
    except Exception as e:
        print(f"❌ 資料庫初始化失敗：{e}")

# ========== 支出分類關鍵字 ==========
EXPENSE_KEYWORDS = {
    '餐飲': ['早餐', '午餐', '晚餐', '宵夜', '飲料', '咖啡', '餐廳', '便當', '麥當勞', '星巴克', '食物', '吃', '喝'],
    '交通': ['油錢', '加油', '停車', '捷運', '公車', '計程車', 'uber', '機車', '汽車', '過路費'],
    '購物': ['衣服', '鞋子', '包包', '化妝品', '保養品', '購物', '網購', '淘寶', '蝦皮', '買'],
    '娛樂': ['電影', '遊戲', 'ktv', '旅遊', '飯店', '景點', '門票', '娛樂', '玩'],
    '居家': ['房租', '水電', '瓦斯', '網路', '電話', '清潔用品', '日用品', '家具'],
    '醫療': ['看病', '藥品', '健檢', '診所', '醫院', '保健食品', '維他命'],
    '教育': ['書籍', '課程', '補習', '學費', '文具', '學習'],
    '其他': ['禮物', '捐款', '罰款', '手續費', '雜費']
}

def classify_expense(description, message):
    """分類支出"""
    full_text = f"{description} {message}".lower()

    for category, keywords in EXPENSE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in full_text:
                return category

    return '其他'

def parse_expense_message(message):
    """解析記帳訊息"""
    message = message.strip()
    print(f"🔍 開始解析訊息：'{message}'")

    # 尋找數字
    numbers = re.findall(r'\d+(?:\.\d+)?', message)
    if not numbers:
        print("❌ 未找到數字")
        return None

    amount = float(numbers[0])
    print(f"💰 找到金額：{amount}")

    # 判斷收入或支出
    is_income = '+' in message or any(word in message for word in ['薪水', '收入', '賺', '領', '獎金', '入帳'])

    # 提取描述
    description = message
    for num in numbers:
        description = description.replace(num, '')

    # 移除常見詞彙
    remove_words = ['元', '塊', '錢', '花了', '花', '買', '付了', '付', '+', '-', '的', '了']
    for word in remove_words:
        description = description.replace(word, '')

    description = description.strip()
    if not description:
        description = "收入" if is_income else "支出"

    print(f"📝 描述：'{description}', 是否為收入：{is_income}")

    return {
        'amount': amount,
        'description': description,
        'is_income': is_income
    }

def execute_database_action(action_data):
    """執行資料庫操作"""
    try:
        if not action_data:
            return None
            
        action_type = action_data.get('action')
        
        if action_type == 'add_expense':
            return add_expense_record(
                action_data.get('user_id'),
                action_data.get('amount'),
                action_data.get('description'),
                action_data.get('category'),
                action_data.get('type', 'expense')
            )
        elif action_type == 'get_statistics':
            return get_statistics(
                action_data.get('user_id'),
                action_data.get('period', 'day')
            )
        elif action_type == 'check_holidays':
            return check_upcoming_holidays()
            
        return None
    except Exception as e:
        print(f"❌ 執行資料庫操作失敗：{e}")
        return None

def add_expense_record(user_id, amount, description, category=None, record_type='expense'):
    """新增記帳記錄"""
    try:
        with db_lock:
            conn = sqlite3.connect('life_assistant.db', timeout=30)
            cursor = conn.cursor()

            taiwan_now = get_taiwan_now()
            date_str = taiwan_now.strftime('%Y-%m-%d')
            created_at = taiwan_now.strftime('%Y-%m-%d %H:%M:%S')

            # 如果沒有指定分類，自動分類
            if not category:
                if record_type == 'income':
                    category = '收入'
                else:
                    category = classify_expense(description, description)

            cursor.execute('''
                INSERT INTO expenses (user_id, date, amount, category, description, type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, date_str, amount, category, description, record_type, created_at))

            record_id = cursor.lastrowid
            conn.commit()
            conn.close()

            print(f"✅ 記錄已新增：ID={record_id}, 分類={category}")
            return {"success": True, "record_id": record_id, "category": category}
    except Exception as e:
        print(f"❌ 新增記錄失敗：{e}")
        return {"success": False, "error": str(e)}

def get_statistics(user_id, period='day'):
    """取得統計資料"""
    try:
        with db_lock:
            conn = sqlite3.connect('life_assistant.db', timeout=30)
            cursor = conn.cursor()

            taiwan_now = get_taiwan_now()

            if period == 'day':
                start_date = taiwan_now.strftime('%Y-%m-%d')
                period_name = "今日"
            elif period == 'week':
                start_of_week = taiwan_now - datetime.timedelta(days=taiwan_now.weekday())
                start_date = start_of_week.strftime('%Y-%m-%d')
                period_name = "本週"
            else:  # month
                start_date = taiwan_now.replace(day=1).strftime('%Y-%m-%d')
                period_name = "本月"

            end_date = taiwan_now.strftime('%Y-%m-%d')

            # 支出統計
            cursor.execute('''
                SELECT category, SUM(amount) FROM expenses 
                WHERE user_id = ? AND date >= ? AND date <= ? AND type = 'expense'
                GROUP BY category ORDER BY SUM(amount) DESC
            ''', (user_id, start_date, end_date))
            
            expense_stats = cursor.fetchall()
            total_expense = sum(amount for _, amount in expense_stats) if expense_stats else 0

            # 收入統計
            cursor.execute('''
                SELECT SUM(amount) FROM expenses 
                WHERE user_id = ? AND date >= ? AND date <= ? AND type = 'income'
            ''', (user_id, start_date, end_date))
            
            income_result = cursor.fetchone()
            total_income = income_result[0] if income_result[0] else 0

            conn.close()
            
            return {
                'period': period_name,
                'total_expense': total_expense,
                'total_income': total_income,
                'balance': total_income - total_expense,
                'expense_by_category': expense_stats
            }
    except Exception as e:
        print(f"❌ 取得統計失敗：{e}")
        return None

def format_statistics(stats):
    """格式化統計訊息"""
    if not stats:
        return "❌ 查詢統計失敗"

    message = f"📊 {stats['period']}帳務統計\n"
    message += "━━━━━━━━━━━━━━━━\n"
    message += f"💰 收入：${stats['total_income']:,.0f}\n"
    message += f"💸 支出：${stats['total_expense']:,.0f}\n"

    if stats['balance'] >= 0:
        message += f"💵 餘額：+${stats['balance']:,.0f}\n\n"
    else:
        message += f"💵 餘額：${stats['balance']:,.0f}\n\n"

    if stats['expense_by_category']:
        message += "📂 支出分類：\n"
        for category, amount in stats['expense_by_category'][:5]:
            percentage = (amount / stats['total_expense']) * 100 if stats['total_expense'] > 0 else 0
            message += f"• {category}：${amount:,.0f} ({percentage:.1f}%)\n"
    else:
        message += "本期間無支出記錄"

    return message

def check_upcoming_holidays():
    """檢查即將到來的節日"""
    upcoming = []
    current_date = get_taiwan_today()
    
    for holiday_name, date_str in IMPORTANT_DATES.items():
        days_until, target_date = calculate_days_until(date_str)
        if days_until is not None and 0 <= days_until <= 30:  # 未來30天內的節日
            upcoming.append({
                'name': holiday_name,
                'date': target_date.strftime('%Y-%m-%d'),
                'days_until': days_until
            })
    
    return sorted(upcoming, key=lambda x: x['days_until'])

def generate_ai_response(user_message: str, user_id: str):
    """使用 AI 生成智能回應並執行相應動作"""
    try:
        if not GOOGLE_AI_API_KEY:
            return "❌ AI 功能未啟用，請設定 API Key"

        # 先嘗試解析是否為記帳訊息
        expense_data = None
        if re.search(r'\d+', user_message):
            expense_data = parse_expense_message(user_message)

        # 獲取當前統計和節日資訊供 AI 參考
        current_stats = get_statistics(user_id, 'day')
        upcoming_holidays = check_upcoming_holidays()
        current_time = get_taiwan_now().strftime('%Y-%m-%d %H:%M')

        # 系統提示詞
        system_prompt = f"""你是一個智能生活助手機器人，角色名稱為「綾小路 清隆」，當前台灣時間是 {current_time}。

🎯 你的核心能力：
1. **記帳管理**：幫用戶記錄收入支出，分析消費模式
2. **節日提醒**：提醒重要節日，建議慶祝方式
3. **生活建議**：根據用戶行為給出實用建議
4. **友善對話**：像朋友一樣自然聊天

📊 當前用戶資訊：
- 今日支出：${current_stats['total_expense'] if current_stats else 0}
- 今日收入：${current_stats['total_income'] if current_stats else 0}
- 即將到來的節日：{upcoming_holidays[:3] if upcoming_holidays else '無'}

🤖 重要節日清單：{IMPORTANT_DATES}

💡 互動規則：
1. 使用繁體中文和適當的 emoji
2. 回應要簡潔有趣，不要超過 300 字
3. 如果用戶提到統計或查詢，提供相關數據
4. 如果提到節日，檢查並提供相關資訊
5. 採取機智冷靜的語調，偶爾溫暖鼓勵

現在請回應用戶的訊息："{user_message}" """

        # 生成 AI 回應
        response = model.generate_content(system_prompt)
        
        if not response.text:
            return "🤔 抱歉，我現在有點累，請稍後再試..."

        ai_response = response.text.strip()
        
        # 限制回應長度
        if len(ai_response) > 300:
            ai_response = ai_response[:280] + "..."

        # 如果是記帳訊息，執行記帳操作
        if expense_data:
            record_result = add_expense_record(
                user_id,
                expense_data['amount'],
                expense_data['description'],
                None,
                'income' if expense_data['is_income'] else 'expense'
            )
            
            if record_result and record_result.get('success'):
                if expense_data['is_income']:
                    ai_response += f"\n\n✅ 已記錄收入：${expense_data['amount']:,.0f} ({record_result.get('category')})"
                else:
                    ai_response += f"\n\n✅ 已記錄支出：${expense_data['amount']:,.0f} ({record_result.get('category')})"

        # 記錄對話
        save_conversation(user_id, user_message, ai_response, expense_data)
        
        return ai_response

    except Exception as e:
        print(f"AI 回應生成失敗：{e}")
        return "🤖 抱歉，我現在有點故障，請稍後再試..."

def save_conversation(user_id, user_message, ai_response, action_taken):
    """保存對話記錄"""
    try:
        with db_lock:
            conn = sqlite3.connect('life_assistant.db', timeout=30)
            cursor = conn.cursor()
            
            created_at = get_taiwan_now().strftime('%Y-%m-%d %H:%M:%S')
            action_str = json.dumps(action_taken, ensure_ascii=False) if action_taken else None
            
            cursor.execute('''
                INSERT INTO conversations (user_id, user_message, ai_response, action_taken, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, user_message, ai_response, action_str, created_at))
            
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"保存對話記錄失敗：{e}")

# ========== Flask 路由 ==========
@app.route("/", methods=['GET'])
def home():
    taiwan_time = get_taiwan_now()
    return f"""🤖 AI 智能生活助手運行中！<br>
台灣時間: {taiwan_time.strftime('%Y-%m-%d %H:%M:%S')}<br>
功能: AI 對話 + 智能記帳 + 節日提醒<br>
資料庫: life_assistant.db"""

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@app.route("/manual_check", methods=['GET'])
def manual_check():
    """手動觸發節日檢查"""
    try:
        check_all_holidays()
        taiwan_time = get_taiwan_now()
        return f"✅ 節日檢查完成 (台灣時間: {taiwan_time.strftime('%Y-%m-%d %H:%M:%S')})", 200
    except Exception as e:
        print(f"手動檢查錯誤：{e}")
        return f"❌ 檢查失敗：{e}", 500

@app.route("/status", methods=['GET'])
def status():
    """顯示機器人狀態"""
    taiwan_time = get_taiwan_now()
    utc_time = datetime.datetime.utcnow()

    status_info = {
        "status": "運行中",
        "taiwan_time": taiwan_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
        "utc_time": utc_time.strftime('%Y-%m-%d %H:%M:%S UTC'),
        "sent_reminders_count": len(sent_reminders),
        "holidays_count": len(IMPORTANT_DATES),
        "database": "life_assistant.db"
    }

    return json.dumps(status_info, ensure_ascii=False, indent=2)

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()

    print(f"\n=== 收到新訊息 ===")
    print(f"用戶ID: {user_id}")
    print(f"訊息內容: '{user_message}'")
    print(f"當前時間: {get_taiwan_now()}")

    try:
        reply_message = None

        # 特殊指令處理
        if user_message == "測試":
            taiwan_time = get_taiwan_now()
            reply_message = f"✅ 機器人運作正常！\n⏰ 台灣時間：{taiwan_time.strftime('%Y-%m-%d %H:%M:%S')}\n💾 資料庫：已連接"
        
        elif user_message in ['說明', '幫助', '功能', '使用說明']:
            reply_message = """🤖 AI 智能生活助手使用說明

💰 記帳功能：
• 早餐65 (或 65早餐)
• 午餐花了120
• +50000薪水 (收入)

📊 查詢統計：
• 今天花了多少錢
• 本週支出  
• 本月收支

📅 節日提醒：
• 查看節日 (或直接說「節日」)
• 手動檢查 (立即檢查節日)

🤖 AI 對話：
• 任何生活問題都可以問我
• 我會自動判斷並執行相應功能

輸入數字開始記帳，或直接跟我聊天！"""

        elif any(keyword in user_message for keyword in ['節日', '查看節日', '重要節日', '紀念日', '生日']):
            reply_message = list_all_holidays()
        
        elif user_message == "手動檢查":
            check_all_holidays()
            taiwan_time = get_taiwan_now()
            reply_message = f"✅ 已執行節日檢查，如有提醒會另外發送訊息\n台灣時間: {taiwan_time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        elif user_message == "時間":
            taiwan_time = get_taiwan_now()
            utc_time = datetime.datetime.utcnow()
            reply_message = f"⏰ 時間資訊：\n台灣時間: {taiwan_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\nUTC時間: {utc_time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        
        elif any(keyword in user_message for keyword in ['今天花', '今日支出', '今天支出', '花了多少']):
            stats = get_statistics(user_id, 'day')
            reply_message = format_statistics(stats)
        
        elif any(keyword in user_message for keyword in ['本週', '這週', '週支出']):
            stats = get_statistics(user_id, 'week')
            reply_message = format_statistics(stats)
        
        elif any(keyword in user_message for keyword in ['本月', '這個月', '月支出', '收支']):
            stats = get_statistics(user_id, 'month')
            reply_message = format_statistics(stats)
        
        else:
            # 使用 AI 處理所有其他訊息
            reply_message = generate_ai_response(user_message, user_id)

        # 發送回覆
        if reply_message:
            print(f"📤 準備回覆：'{reply_message[:50]}...'")
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_message)
            )
            print("✅ 回覆成功")

    except Exception as e:
        print(f"❌ 處理訊息錯誤：{e}")
        import traceback
        traceback.print_exc()

        try:
            error_message = f"❌ 系統錯誤，請稍後再試\n錯誤類型：{type(e).__name__}"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=error_message)
            )
        except Exception as reply_error:
            print(f"❌ 連錯誤回覆都失敗：{reply_error}")


def run_scheduler():
    """運行排程器（每天台灣時間 00:00 和 12:00 檢查節日）"""
    # 每天台灣時間凌晨00:00檢查
    schedule.every().day.at("00:00").do(check_all_holidays)
    # 每天台灣時間中午12:00檢查  
    schedule.every().day.at("12:00").do(check_all_holidays)
    # 每天台灣時間凌晨01:00清除舊提醒記錄
    schedule.every().day.at("01:00").do(clear_old_reminders)
    
    print(f"排程器已啟動 - 將在每天台灣時間 00:00 和 12:00 執行檢查")
    print(f"當前台灣時間: {get_taiwan_now()}")
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)  # 每分鐘檢查一次排程
        except Exception as e:
            print(f"排程器錯誤：{e}")
            time.sleep(60)


# ========== 初始化和啟動 ==========
if __name__ == "__main__":
    print("🚀 正在啟動 AI 智能生活助手...")
    print(f"⏰ 當前台灣時間：{get_taiwan_now()}")

    # 初始化資料庫
    init_database()

    # 在背景執行排程器
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # 執行啟動檢查
    print("執行啟動檢查...")
    check_all_holidays()

    # 啟動 Flask 應用
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 應用程式啟動在 port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
