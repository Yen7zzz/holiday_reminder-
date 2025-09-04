import os
import datetime
import pytz
import json
import re
import sqlite3
from threading import Lock
from collections import defaultdict

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import schedule
import time
import threading
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

# ==================== 節日提醒功能 ====================
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

sent_reminders = set()

# ==================== 記帳功能 ====================
# 支出分類關鍵字
EXPENSE_KEYWORDS = {
    '餐飲': ['早餐', '午餐', '晚餐', '宵夜', '飲料', '咖啡', '餐廳', '便當', '麥當勞', '星巴克', '食物', '吃', '喝', '買吃的', '點餐'],
    '交通': ['油錢', '加油', '停車', '捷運', '公車', '計程車', 'uber', '機車', '汽車', '過路費', '車費', '油站'],
    '購物': ['衣服', '鞋子', '包包', '化妝品', '保養品', '購物', '網購', '淘寶', '蝦皮', 'momo', '買', '商店'],
    '娛樂': ['電影', '遊戲', 'ktv', '旅遊', '飯店', '景點', '門票', '娛樂', '玩', '看電影'],
    '居家': ['房租', '水電', '瓦斯', '網路', '電話', '清潔用品', '日用品', '家具', '修繕', '家用'],
    '醫療': ['看病', '藥品', '健檢', '診所', '醫院', '保健食品', '維他命', '藥局'],
    '教育': ['書籍', '課程', '補習', '學費', '文具', '學習', '買書'],
    '其他': ['禮物', '捐款', '罰款', '手續費', '雜費', '其他']
}

INCOME_KEYWORDS = {
    '薪資': ['薪水', '獎金', '加班費', '年終', '工資'],
    '投資': ['股票', '基金', '利息', '股利', '投資', '賺錢'],
    '副業': ['兼職', '接案', '副業', '外快', '打工'],
    '其他收入': ['禮金', '退稅', '退費', '中獎', '收入']
}

def get_taiwan_now():
    """取得台灣當前時間"""
    return datetime.datetime.now(TAIWAN_TZ)

def get_taiwan_today():
    """取得台灣今天的日期"""
    return get_taiwan_now().date()

# ==================== 資料庫初始化 ====================
def init_database():
    """初始化資料庫"""
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
                raw_message TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        
        # 預算設定表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                category TEXT NOT NULL,
                monthly_budget REAL NOT NULL,
                year_month TEXT NOT NULL,
                UNIQUE(user_id, category, year_month)
            )
        ''')
        
        conn.commit()
        conn.close()

# ==================== 對話式記帳 AI 解析 ====================
def extract_expense_from_natural_text(message):
    """從自然語言中提取記帳資訊"""
    message = message.strip()
    
    # 常見的記帳模式
    patterns = [
        # 直接格式：早餐 65, 65 早餐
        (r'^([+\-]?)(\d+\.?\d*)\s+(.+)$', 'amount_first'),
        (r'^(.+?)\s+([+\-]?)(\d+\.?\d*)(?:元|塊|錢)?$', 'desc_first'),
        
        # 自然語言格式
        (r'.*(?:花了|花|付了|買|消費|支出).*?(\d+\.?\d*)(?:元|塊|錢).*?([^0-9\+\-]+)', 'natural_expense'),
        (r'.*?([^0-9\+\-]+).*?(?:花了|花|付了|買|消費|支出).*?(\d+\.?\d*)(?:元|塊|錢)', 'natural_expense_reverse'),
        
        # 收入格式
        (r'.*(?:賺了|收入|領了|得到|薪水).*?(\d+\.?\d*)(?:元|塊|錢).*?([^0-9\+\-]*)', 'natural_income'),
        (r'.*?([^0-9\+\-]+).*?(?:賺了|收入|領了|得到|薪水).*?(\d+\.?\d*)(?:元|塊|錢)', 'natural_income_reverse'),
        
        # 簡單金額
        (r'^([+\-]?)(\d+\.?\d*)(?:元|塊|錢)?$', 'amount_only')
    ]
    
    for pattern, pattern_type in patterns:
        match = re.search(pattern, message)
        if match:
            return parse_match_result(match, pattern_type, message)
    
    return None

def parse_match_result(match, pattern_type, original_message):
    """解析正規表達式匹配結果"""
    groups = match.groups()
    
    if pattern_type == 'amount_first':
        sign = groups[0]
        amount = float(groups[1])
        description = groups[2]
        is_income = sign == '+' or is_income_related(description)
    
    elif pattern_type == 'desc_first':
        description = groups[0]
        sign = groups[1]
        amount = float(groups[2])
        is_income = sign == '+' or is_income_related(description)
    
    elif pattern_type == 'natural_expense':
        amount = float(groups[0])
        description = groups[1].strip()
        is_income = False
    
    elif pattern_type == 'natural_expense_reverse':
        description = groups[0].strip()
        amount = float(groups[1])
        is_income = False
    
    elif pattern_type == 'natural_income':
        amount = float(groups[0])
        description = groups[1].strip() if groups[1] else "收入"
        is_income = True
    
    elif pattern_type == 'natural_income_reverse':
        description = groups[0].strip()
        amount = float(groups[1])
        is_income = True
    
    elif pattern_type == 'amount_only':
        sign = groups[0]
        amount = float(groups[1])
        description = "支出" if sign != '+' else "收入"
        is_income = sign == '+'
    
    else:
        return None
    
    # 清理描述
    description = clean_description(description)
    
    return {
        'amount': amount,
        'description': description,
        'is_income': is_income,
        'confidence': calculate_confidence(original_message, description, amount)
    }

def is_income_related(text):
    """判斷是否為收入相關"""
    income_indicators = ['薪水', '獎金', '收入', '賺', '領', '得到', '工資', '兼職', '打工']
    return any(indicator in text for indicator in income_indicators)

def clean_description(description):
    """清理描述文字"""
    # 移除常見的無用詞彙
    remove_words = ['了', '的', '在', '去', '花', '買', '付', '錢', '元', '塊', '支出', '消費']
    for word in remove_words:
        description = description.replace(word, '')
    
    return description.strip() or "支出"

def calculate_confidence(original, description, amount):
    """計算解析信心度"""
    confidence = 0.8
    
    # 如果包含明確的金錢詞彙，提高信心度
    money_words = ['花', '買', '付', '錢', '元', '塊', '消費', '支出']
    if any(word in original for word in money_words):
        confidence += 0.1
    
    # 如果描述合理，提高信心度
    if len(description) > 1 and description != "支出":
        confidence += 0.05
    
    return min(confidence, 1.0)

def classify_expense_smart(description, message):
    """智能分類支出"""
    full_text = f"{description} {message}".lower()
    
    for category, keywords in EXPENSE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in full_text:
                return category
    
    return '其他'

def classify_income_smart(description, message):
    """智能分類收入"""
    full_text = f"{description} {message}".lower()
    
    for category, keywords in INCOME_KEYWORDS.items():
        for keyword in keywords:
            if keyword in full_text:
                return category
    
    return '其他收入'

# ==================== 記帳功能 ====================
def add_expense_record(user_id, amount, description, is_income, raw_message):
    """新增記帳記錄"""
    with db_lock:
        conn = sqlite3.connect('life_assistant.db')
        cursor = conn.cursor()
        
        taiwan_now = get_taiwan_now()
        date_str = taiwan_now.strftime('%Y-%m-%d')
        created_at = taiwan_now.strftime('%Y-%m-%d %H:%M:%S')
        
        if is_income:
            category = classify_income_smart(description, raw_message)
            record_type = 'income'
        else:
            category = classify_expense_smart(description, raw_message)
            record_type = 'expense'
        
        cursor.execute('''
            INSERT INTO expenses (user_id, date, amount, category, description, type, raw_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, date_str, amount, category, description, record_type, raw_message, created_at))
        
        record_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return record_id, category

def get_expense_statistics(user_id, period='month'):
    """取得記帳統計"""
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
            SELECT category, SUM(amount) 
            FROM expenses 
            WHERE user_id = ? AND date >= ? AND date <= ? AND type = 'expense'
            GROUP BY category
            ORDER BY SUM(amount) DESC
        ''', (user_id, start_date, end_date))
        
        expense_stats = cursor.fetchall()
        total_expense = sum(amount for _, amount in expense_stats)
        
        # 收入統計
        cursor.execute('''
            SELECT SUM(amount) 
            FROM expenses 
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

# ==================== 節日提醒功能 ====================
def calculate_days_until(target_date_str):
    """計算距離目標日期還有幾天"""
    try:
        target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
        current_year = get_taiwan_today().year
        current_date = get_taiwan_today()

        if any(keyword in target_date_str for keyword in ["生日", "紀念日", "情人節", "七夕", "聖誕節"]):
            target_date = target_date.replace(year=current_year)
            if target_date < current_date:
                target_date = target_date.replace(year=current_year + 1)

        days_until = (target_date - current_date).days
        return days_until, target_date
    except ValueError:
        return None, None

def list_all_holidays():
    """列出所有節日"""
    taiwan_time = get_taiwan_now()
    message = f"📅 重要節日 (台灣時間: {taiwan_time.strftime('%m-%d %H:%M')})：\n\n"
    for holiday_name, date_str in IMPORTANT_DATES.items():
        days_until, target_date = calculate_days_until(date_str)
        if days_until is not None:
            message += f"• {holiday_name}：{target_date.strftime('%m月%d日')} (還有{days_until}天)\n"
    return message

# ==================== 訊息處理 ====================
def is_expense_query(message):
    """判斷是否為記帳查詢"""
    query_keywords = [
        '今天花', '今日支出', '本週支出', '本月支出', 
        '花了多少', '支出統計', '收支', '帳務',
        '今天', '本週', '本月'
    ]
    return any(keyword in message for keyword in query_keywords)

def is_holiday_query(message):
    """判斷是否為節日查詢"""
    holiday_keywords = [
        '節日', '紀念日', '生日', '查看節日', 
        '重要日子', '提醒', '檢查節日'
    ]
    return any(keyword in message for keyword in holiday_keywords)

def contains_number(message):
    """判斷訊息是否包含數字（可能是記帳）"""
    return bool(re.search(r'\d+', message))

@app.route("/", methods=['GET'])
def home():
    taiwan_time = get_taiwan_now()
    return f"智能生活助手正在運行！🤖💰📅<br>台灣時間: {taiwan_time.strftime('%Y-%m-%d %H:%M:%S')}"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature")
        abort(400)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    
    try:
        reply_message = ""
        
        # 節日相關查詢
        if is_holiday_query(user_message) or '節日' in user_message:
            reply_message = list_all_holidays()
        
        # 記帳統計查詢
        elif is_expense_query(user_message):
            if '今天' in user_message or '今日' in user_message:
                stats = get_expense_statistics(user_id, 'day')
            elif '本週' in user_message:
                stats = get_expense_statistics(user_id, 'week')
            else:
                stats = get_expense_statistics(user_id, 'month')
            
            reply_message = format_expense_statistics(stats)
        
        # 說明功能
        elif user_message in ['說明', '幫助', '功能', '怎麼用']:
            reply_message = get_help_message()
        
        # 嘗試解析為記帳
        elif contains_number(user_message):
            expense_data = extract_expense_from_natural_text(user_message)
            
            if expense_data and expense_data['confidence'] > 0.6:
                record_id, category = add_expense_record(
                    user_id, 
                    expense_data['amount'], 
                    expense_data['description'], 
                    expense_data['is_income'],
                    user_message
                )
                
                if expense_data['is_income']:
                    reply_message = f"✅ 收入記錄成功！\n💰 +${expense_data['amount']:,.0f}\n📂 {category}\n📝 {expense_data['description']}"
                else:
                    reply_message = f"✅ 支出記錄成功！\n💸 ${expense_data['amount']:,.0f}\n📂 {category}\n📝 {expense_data['description']}"
            else:
                reply_message = "🤔 我好像沒理解您的意思\n\n💡 您可以這樣說：\n• 買早餐花了65塊\n• 今天花了多少錢\n• 查看節日\n\n輸入「說明」查看完整功能"
        
        # 其他一般對話
        else:
            reply_message = "🤖 我是您的智能生活助手！\n\n我可以幫您：\n💰 記帳：直接說「買早餐65塊」\n📅 節日：輸入「查看節日」\n📊 統計：問「今天花了多少錢」\n\n輸入「說明」查看完整功能"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_message)
        )
        
    except Exception as e:
        print(f"處理訊息錯誤：{e}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ 處理失敗，請稍後再試")
        )

def format_expense_statistics(stats):
    """格式化記帳統計"""
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
    
    return message

def get_help_message():
    """取得完整說明"""
    return """🤖 智能生活助手使用說明

💰 記帳功能：
• 買早餐花了65塊
• 中午吃麥當勞120元
• 加油站加了800塊油
• 薪水收入50000

📊 查詢統計：
• 今天花了多少錢
• 本週支出統計  
• 本月收支狀況

📅 節日提醒：
• 查看節日
• 重要紀念日

🎯 特色功能：
• 自然語言記帳，想怎麼說就怎麼說
• 智能自動分類
• 即時統計分析
• 節日自動提醒

💬 直接跟我聊天就能記帳，超簡單！"""

# 初始化資料庫
init_database()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
