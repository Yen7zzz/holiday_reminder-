import os
import datetime
import pytz
import json
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

def get_taiwan_now():
    """取得台灣當前時間"""
    return datetime.datetime.now(TAIWAN_TZ)

def get_taiwan_today():
    """取得台灣今天的日期"""
    return get_taiwan_now().date()

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

            # AI 對話記錄表（新增）
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

            conn.commit()
            conn.close()
            print("✅ 資料庫初始化成功")
    except Exception as e:
        print(f"❌ 資料庫初始化失敗：{e}")

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

def add_expense_record(user_id, amount, description, category, record_type):
    """新增記帳記錄"""
    try:
        with db_lock:
            conn = sqlite3.connect('life_assistant.db', timeout=30)
            cursor = conn.cursor()

            taiwan_now = get_taiwan_now()
            date_str = taiwan_now.strftime('%Y-%m-%d')
            created_at = taiwan_now.strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute('''
                INSERT INTO expenses (user_id, date, amount, category, description, type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, date_str, amount, category, description, record_type, created_at))

            record_id = cursor.lastrowid
            conn.commit()
            conn.close()

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
            elif period == 'week':
                start_of_week = taiwan_now - datetime.timedelta(days=taiwan_now.weekday())
                start_date = start_of_week.strftime('%Y-%m-%d')
            else:  # month
                start_date = taiwan_now.replace(day=1).strftime('%Y-%m-%d')

            end_date = taiwan_now.strftime('%Y-%m-%d')

            # 支出統計
            cursor.execute('''
                SELECT category, SUM(amount) FROM expenses 
                WHERE user_id = ? AND date >= ? AND date <= ? AND type = 'expense'
                GROUP BY category ORDER BY SUM(amount) DESC
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
                'period': period,
                'total_expense': total_expense,
                'total_income': total_income,
                'balance': total_income - total_expense,
                'expense_by_category': expense_stats
            }
    except Exception as e:
        print(f"❌ 取得統計失敗：{e}")
        return None

def check_upcoming_holidays():
    """檢查即將到來的節日"""
    upcoming = []
    current_date = get_taiwan_today()
    
    for holiday_name, date_str in IMPORTANT_DATES.items():
        try:
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            current_year = current_date.year
            
            # 年度循環節日處理
            if any(keyword in holiday_name for keyword in ["生日", "紀念日", "情人節", "七夕", "聖誕節"]):
                target_date = target_date.replace(year=current_year)
                if target_date < current_date:
                    target_date = target_date.replace(year=current_year + 1)
            
            days_until = (target_date - current_date).days
            
            if 0 <= days_until <= 30:  # 未來30天內的節日
                upcoming.append({
                    'name': holiday_name,
                    'date': target_date.strftime('%Y-%m-%d'),
                    'days_until': days_until
                })
        except:
            continue
    
    return sorted(upcoming, key=lambda x: x['days_until'])

def generate_ai_response(user_message: str, user_id: str):
    """使用 AI 生成智能回應並執行相應動作"""
    try:
        if not GOOGLE_AI_API_KEY:
            return "❌ AI 功能未啟用，請設定 API Key"

        # 獲取當前統計和節日資訊供 AI 參考
        current_stats = get_statistics(user_id, 'day')
        upcoming_holidays = check_upcoming_holidays()
        current_time = get_taiwan_now().strftime('%Y-%m-%d %H:%M')

        # 系統提示詞
        system_prompt = f"""你是一個智能生活助手機器人，當前台灣時間是 {current_time}。

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
1. 如果用戶提到數字和消費，自動判斷是否需要記帳
2. 如果詢問統計或花費，提供相關數據
3. 如果提到節日，檢查並提供相關資訊
4. 使用繁體中文和適當的 emoji
5. 回應要簡潔有趣，不要超過 200 字

⚙️ 動作執行格式：
如果需要執行動作，在回應後加上 JSON 格式的動作指令：
{{
    "action": "add_expense|get_statistics|check_holidays",
    "user_id": "{user_id}",
    "amount": 數字（記帳時），
    "description": "描述",
    "category": "分類",
    "type": "expense|income",
    "period": "day|week|month"（查詢統計時）
}}

現在請回應用戶的訊息："{user_message}" """

        # 生成 AI 回應
        response = model.generate_content(system_prompt)
        
        if not response.text:
            return "🤔 抱歉，我現在有點累，請稍後再試..."

        ai_response = response.text.strip()
        
        # 嘗試從回應中提取動作指令
        action_data = None
        if '{"action"' in ai_response:
            try:
                # 提取 JSON 部分
                json_start = ai_response.find('{"action"')
                json_end = ai_response.find('}', json_start) + 1
                json_str = ai_response[json_start:json_end]
                action_data = json.loads(json_str)
                
                # 從回應中移除 JSON 部分
                ai_response = ai_response[:json_start].strip()
                
            except:
                pass

        # 執行動作
        if action_data:
            action_result = execute_database_action(action_data)
            if action_result:
                # 根據動作結果調整回應
                if action_data.get('action') == 'add_expense' and action_result.get('success'):
                    ai_response += f"\n✅ 已記錄到 {action_result.get('category')} 分類"

        # 記錄對話
        save_conversation(user_id, user_message, ai_response, action_data)
        
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
            action_str = json.dumps(action_taken) if action_taken else None
            
            cursor.execute('''
                INSERT INTO conversations (user_id, user_message, ai_response, action_taken, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, user_message, ai_response, action_str, created_at))
            
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"保存對話記錄失敗：{e}")

# 自動節日檢查（簡化版）
def auto_holiday_check():
    """自動節日檢查並發送提醒"""
    try:
        upcoming = check_upcoming_holidays()
        
        for holiday in upcoming:
            days = holiday['days_until']
            if days in [7, 5, 3, 1, 0]:
                message = f"🔔 提醒：{holiday['name']} 還有 {days} 天！"
                if days == 0:
                    message = f"🎉 今天是 {holiday['name']}！"
                
                line_bot_api.push_message(YOUR_USER_ID, TextSendMessage(text=message))
                print(f"已發送節日提醒：{holiday['name']} - {days}天")
                
    except Exception as e:
        print(f"節日檢查失敗：{e}")

@app.route("/", methods=['GET'])
def home():
    return f"""🤖 AI 智能生活助手運行中！<br>台灣時間: {get_taiwan_now()}<br>功能: AI 對話 + 智能記帳 + 節日提醒"""

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()

    print(f"📨 收到訊息：{user_message}")

    try:
        # 使用 AI 處理所有訊息
        ai_response = generate_ai_response(user_message, user_id)
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=ai_response)
        )
        
        print(f"✅ AI 回應：{ai_response[:50]}...")

    except Exception as e:
        print(f"❌ 處理失敗：{e}")
        error_message = "🤖 抱歉，系統出了點小問題，請稍後再試..."
        
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=error_message)
            )
        except:
            pass

def run_scheduler():
    """運行排程器"""
    schedule.every().day.at("09:00").do(auto_holiday_check)
    schedule.every().day.at("18:00").do(auto_holiday_check)
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(3600)  # 每小時檢查一次
        except:
            time.sleep(3600)

# 初始化
print("🚀 啟動 AI 智能生活助手...")
init_database()

# 背景排程器
scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
