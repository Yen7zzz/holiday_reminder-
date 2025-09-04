import os
import datetime
import pytz
import json
import re
import sqlite3
from threading import Lock

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from flask import Flask, request, abort

app = Flask(__name__)

# 設定台灣時區
TAIWAN_TZ = pytz.timezone('Asia/Taipei')

# Line Bot 設定
CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN', 'KRk+bAgSSozHdXGPpcFYLSYMk+4T27W/OTDDJmECpMT4uKQgQDGkLGl5+IRVURdrQ7RHLF1vUqnQU542ZFBWZJZapRi/zg0iuJJeAGM7kXIhFJqHAeKv88+yqHayFXa140YGdC2Va1wahK9QNfV8uwdB04t89/1O/w1cDnyilFU=')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET', 'b7f5d7b95923fbc5f494619885a68a04')
YOUR_USER_ID = os.environ.get('YOUR_USER_ID', 'Ueeef67149e409ffe30e60328a379e5a0')

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 資料庫鎖
db_lock = Lock()

# 節日資料
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

# 支出分類關鍵字
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

def get_taiwan_now():
    """取得台灣當前時間"""
    return datetime.datetime.now(TAIWAN_TZ)

def init_database():
    """初始化資料庫"""
    try:
        with db_lock:
            conn = sqlite3.connect('life_assistant.db')
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
            
            conn.commit()
            conn.close()
            print("✅ 資料庫初始化成功")
    except Exception as e:
        print(f"❌ 資料庫初始化失敗：{e}")

def parse_expense_message(message):
    """解析記帳訊息"""
    message = message.strip()
    print(f"🔍 開始解析訊息：'{message}'")
    
    # 尋找數字
    numbers = re.findall(r'\d+\.?\d*', message)
    if not numbers:
        print("❌ 未找到數字")
        return None
    
    amount = float(numbers[0])
    print(f"💰 找到金額：{amount}")
    
    # 判斷收入或支出
    is_income = '+' in message or any(word in message for word in ['薪水', '收入', '賺', '領', '獎金'])
    
    # 提取描述 - 移除數字和單位詞
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

def classify_expense(description, message):
    """分類支出"""
    full_text = f"{description} {message}".lower()
    
    for category, keywords in EXPENSE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in full_text:
                return category
    
    return '其他'

def add_expense_record(user_id, amount, description, is_income):
    """新增記帳記錄"""
    try:
        with db_lock:
            conn = sqlite3.connect('life_assistant.db')
            cursor = conn.cursor()
            
            taiwan_now = get_taiwan_now()
            date_str = taiwan_now.strftime('%Y-%m-%d')
            created_at = taiwan_now.strftime('%Y-%m-%d %H:%M:%S')
            
            if is_income:
                category = '收入'
                record_type = 'income'
            else:
                category = classify_expense(description, description)
                record_type = 'expense'
            
            cursor.execute('''
                INSERT INTO expenses (user_id, date, amount, category, description, type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, date_str, amount, category, description, record_type, created_at))
            
            record_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            print(f"✅ 記錄已新增：ID={record_id}, 分類={category}")
            return record_id, category
    
    except Exception as e:
        print(f"❌ 新增記錄失敗：{e}")
        return None, None

def get_statistics(user_id, period='day'):
    """取得統計"""
    try:
        with db_lock:
            conn = sqlite3.connect('life_assistant.db')
            cursor = conn.cursor()
            
            taiwan_now = get_taiwan_now()
            
            if period == 'day':
                start_date = taiwan_now.strftime('%Y-%m-%d')
                period_name = "今日"
            elif period == 'week':
                start_of_week = taiwan_now - datetime.timedelta(days=taiwan_now.weekday())
                start_date = start_of_week.strftime('%Y-%m-%d')
                period_name = "本週"
            else:
                start_date = taiwan_now.replace(day=1).strftime('%Y-%m-%d')
                period_name = "本月"
            
            end_date = taiwan_now.strftime('%Y-%m-%d')
            
            # 支出統計
            cursor.execute('''
                SELECT category, SUM(amount) FROM expenses 
                WHERE user_id = ? AND date >= ? AND date <= ? AND type = 'expense'
                GROUP BY category
                ORDER BY SUM(amount) DESC
            ''', (user_id, start_date, end_date))
            
            expense_stats = cursor.fetchall()
            total_expense = sum(amount for _, amount in expense_stats)
            
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

def list_holidays():
    """列出節日"""
    taiwan_time = get_taiwan_now()
    message = f"📅 重要節日：\n\n"
    
    for holiday_name, date_str in IMPORTANT_DATES.items():
        try:
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            current_year = taiwan_time.year
            current_date = taiwan_time.date()
            
            # 調整年份
            target_date = target_date.replace(year=current_year)
            if target_date < current_date:
                target_date = target_date.replace(year=current_year + 1)
            
            days_until = (target_date - current_date).days
            message += f"• {holiday_name}：{target_date.strftime('%m月%d日')} (還有{days_until}天)\n"
        except:
            continue
    
    return message

@app.route("/", methods=['GET'])
def home():
    taiwan_time = get_taiwan_now()
    return f"🤖 智能生活助手運行中！<br>台灣時間: {taiwan_time.strftime('%Y-%m-%d %H:%M:%S')}"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ Invalid signature")
        abort(400)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    
    print(f"\n=== 收到新訊息 ===")
    print(f"用戶ID: {user_id}")
    print(f"訊息內容: '{user_message}'")
    
    try:
        reply_message = None
        
        # 1. 測試功能
        if user_message == "測試":
            reply_message = "✅ 機器人運作正常！"
            print("🧪 回應測試訊息")
        
        # 2. 說明功能
        elif user_message in ['說明', '幫助', '功能', '使用說明']:
            reply_message = """🤖 智能生活助手使用說明

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

輸入「測試」檢查機器人狀態"""
            print("📖 回應說明")
        
        # 3. 節日查詢 - 擴大匹配範圍
        elif any(keyword in user_message for keyword in ['節日', '查看節日', '重要節日', '紀念日', '生日']):
            reply_message = list_holidays()
            print("📅 回應節日查詢")
        
        # 4. 統計查詢 - 擴大匹配範圍
        elif any(keyword in user_message for keyword in ['今天花', '今日支出', '今天支出', '花了多少']):
            stats = get_statistics(user_id, 'day')
            reply_message = format_statistics(stats)
            print("📊 回應今日統計")
            
        elif any(keyword in user_message for keyword in ['本週', '這週', '週支出']):
            stats = get_statistics(user_id, 'week')
            reply_message = format_statistics(stats)
            print("📊 回應本週統計")
            
        elif any(keyword in user_message for keyword in ['本月', '這個月', '月支出', '收支']):
            stats = get_statistics(user_id, 'month')
            reply_message = format_statistics(stats)
            print("📊 回應本月統計")
        
        # 5. 記帳功能 - 包含數字的訊息
        elif re.search(r'\d+', user_message):
            print("💰 判斷為記帳訊息")
            expense_data = parse_expense_message(user_message)
            
            if expense_data:
                print(f"✅ 解析成功：{expense_data}")
                record_id, category = add_expense_record(
                    user_id, 
                    expense_data['amount'], 
                    expense_data['description'], 
                    expense_data['is_income']
                )
                
                if record_id:
                    if expense_data['is_income']:
                        reply_message = f"✅ 收入記錄成功！\n💰 +${expense_data['amount']:,.0f}\n📂 {category}\n📝 {expense_data['description']}"
                    else:
                        reply_message = f"✅ 支出記錄成功！\n💸 ${expense_data['amount']:,.0f}\n📂 {category}\n📝 {expense_data['description']}"
                else:
                    reply_message = "❌ 記帳失敗，請稍後再試"
            else:
                reply_message = "🤔 無法理解您的記帳格式\n\n請嘗試：\n• 早餐65\n• 午餐花了120\n• +50000薪水"
            print("💰 處理記帳完成")
        
        # 6. 其他對話
        else:
            reply_message = f"🤖 您好！我是智能生活助手\n\n我可以幫您：\n💰 記帳：「午餐花了80」\n📊 統計：「今天花了多少錢」\n📅 節日：「查看節日」\n\n輸入「說明」查看完整功能"
            print("💬 回應一般對話")
        
        # 確保有回覆訊息
        if reply_message:
            print(f"📤 準備回覆：'{reply_message[:50]}...'")
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_message)
            )
            print("✅ 回覆成功")
        else:
            print("❌ 沒有生成回覆訊息")
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🤔 抱歉，我沒有理解您的訊息，請輸入「說明」查看功能")
            )
        
    except Exception as e:
        print(f"❌ 處理訊息錯誤：{e}")
        import traceback
        traceback.print_exc()
        
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"❌ 系統錯誤，請稍後再試\n錯誤詳情：{str(e)}")
            )
        except Exception as reply_error:
            print(f"❌ 連錯誤回覆都失敗：{reply_error}")

# 初始化
print("🚀 正在啟動智能生活助手...")
init_database()
print(f"⏰ 當前台灣時間：{get_taiwan_now()}")

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 應用程式啟動在 port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
