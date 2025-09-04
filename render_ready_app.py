import os
import datetime
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import schedule
import time
import threading
from flask import Flask, request, abort
import json

app = Flask(__name__)

# Line Bot 設定 - 從環境變數讀取
CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN', 'KRk+bAgSSozHdXGPpcFYLSYMk+4T27W/OTDDJmECpMT4uKQgQDGkLGl5+IRVURdrQ7RHLF1vUqnQU542ZFBWZJZapRi/zg0iuJJeAGM7kXIhFJqHAeKv88+yqHayFXa140YGdC2Va1wahK9QNfV8uwdB04t89/1O/w1cDnyilFU=')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET', 'b7f5d7b95923fbc5f494619885a68a04')
YOUR_USER_ID = os.environ.get('YOUR_USER_ID', 'Ueeef67149e409ffe30e60328a379e5a0')

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 儲存重要節日的字典
IMPORTANT_DATES = {
    "七夕": "2025-08-29",
    "老婆生日": "2025-02-26",
    "結婚紀念日": "2025-01-16",
    "情人節": "2025-02-14",
    "聖誕節": "2025-12-25",
    "蝦皮慶典": "2025-09-09",
}

def calculate_days_until(target_date_str):
    """計算距離目標日期還有幾天"""
    try:
        target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
        current_year = datetime.date.today().year
        current_date = datetime.date.today()

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
        print(f"提醒訊息已發送：{holiday_name} - {days_until}天")
    except Exception as e:
        print(f"發送訊息失敗：{e}")

def check_all_holidays():
    """檢查所有節日並發送提醒"""
    print(f"正在檢查節日提醒... {datetime.datetime.now()}")
    
    for holiday_name, date_str in IMPORTANT_DATES.items():
        days_until, target_date = calculate_days_until(date_str)
        
        if days_until is not None:
            print(f"{holiday_name}: 還有 {days_until} 天")
            if days_until in [7, 5, 3, 1, 0]:
                send_reminder_message(holiday_name, days_until, target_date)

def add_new_holiday(holiday_name, date_str):
    """添加新的節日"""
    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
        IMPORTANT_DATES[holiday_name] = date_str
        return f"✅ 已成功添加節日：{holiday_name} ({date_str})"
    except ValueError:
        return "❌ 日期格式錯誤！請使用 YYYY-MM-DD 格式"

def list_all_holidays():
    """列出所有節日"""
    if not IMPORTANT_DATES:
        return "目前沒有設定任何重要節日"
    
    message = "📅 已設定的重要節日：\n\n"
    for holiday_name, date_str in IMPORTANT_DATES.items():
        days_until, target_date = calculate_days_until(date_str)
        if days_until is not None:
            message += f"• {holiday_name}：{target_date.strftime('%Y年%m月%d日')} (還有{days_until}天)\n"
    
    return message

@app.route("/", methods=['GET'])
def home():
    return "節日提醒機器人正在運行中！🤖"

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

@app.route("/manual_check", methods=['GET'])
def manual_check():
    """手動觸發節日檢查 - 供外部排程服務使用"""
    try:
        check_all_holidays()
        return "✅ 節日檢查完成", 200
    except Exception as e:
        print(f"手動檢查錯誤：{e}")
        return f"❌ 檢查失敗：{e}", 500

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    
    if user_message == "查看節日":
        reply_message = list_all_holidays()
    elif user_message.startswith("添加節日"):
        parts = user_message.split(" ")
        if len(parts) == 3:
            _, holiday_name, date_str = parts
            reply_message = add_new_holiday(holiday_name, date_str)
        else:
            reply_message = "❌ 格式錯誤！\n正確格式：添加節日 節日名稱 YYYY-MM-DD\n例如：添加節日 週年慶 2025-06-01"
    elif user_message == "手動檢查":
        check_all_holidays()
        reply_message = "✅ 已執行節日檢查，如有提醒會另外發送訊息"
    elif user_message == "說明":
        reply_message = """🤖 節日提醒機器人使用說明：

📍 可用指令：
• 查看節日 - 查看所有已設定的節日
• 添加節日 [名稱] [日期] - 添加新節日
• 手動檢查 - 立即檢查是否需要提醒
• 說明 - 顯示此說明

📅 自動提醒時機：
• 節日前7天、5天、3天、1天及當天
• 每天凌晨12點和中午12點自動檢查

💡 日期格式：YYYY-MM-DD
例如：2025-05-20"""
    else:
        reply_message = "請輸入「說明」查看可用指令，或輸入「查看節日」查看已設定的節日"
    
    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_message)
        )
    except Exception as e:
        print(f"回覆訊息失敗：{e}")

def run_scheduler():
    """運行排程器"""
    # 每天凌晨12點檢查
    schedule.every().day.at("00:00").do(check_all_holidays)
    # 每天中午12點檢查
    schedule.every().day.at("12:00").do(check_all_holidays)
    
    print("排程器已啟動 - 將在每天 00:00 和 12:00 執行檢查")
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except Exception as e:
            print(f"排程器錯誤：{e}")
            time.sleep(60)

# 在背景執行排程器
scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()

# 執行啟動檢查
print("執行啟動檢查...")
check_all_holidays()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)