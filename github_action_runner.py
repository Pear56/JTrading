import os
import json
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

# ==========================================
# 配置读取 (优先从环境变量读取)
# ==========================================
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.126.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
# 订阅者邮箱，多个邮箱用逗号分隔
SUBSCRIBER_EMAILS = os.environ.get("SUBSCRIBER_EMAILS", "").split(",")
# Server酱 Key
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY")

# ==========================================
# RSI 阈值配置
# ==========================================
RSI_BUY_THRESHOLD = int(os.environ.get("RSI_BUY_THRESHOLD", 40))
RSI_SELL_THRESHOLD = int(os.environ.get("RSI_SELL_THRESHOLD", 70))

def fetch_rsi_and_price():
    """
    获取 RSI 和 价格数据
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始获取数据...")
    rsi_value = None
    latest_price = None
    
    try:
        url = 'https://cn.investing.com/etfs/huatai-pinebridge-csi-div-low-vol-technical'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')

        # 优先直接查找 ID 为 __NEXT_DATA__ 的脚本
        script = soup.find('script', id='__NEXT_DATA__')
        
        if script and script.string:
            try:
                data = json.loads(script.string)
                
                # 递归查找 key 为 technicalDaily 的字典
                def find_key(obj, key):
                    if isinstance(obj, dict):
                        if key in obj:
                            return obj[key]
                        for k, v in obj.items():
                            result = find_key(v, key)
                            if result:
                                return result
                    elif isinstance(obj, list):
                        for item in obj:
                            result = find_key(item, key)
                            if result:
                                return result
                    return None

                tech_daily = find_key(data, 'technicalDaily')
                if tech_daily:
                    rsi_data = tech_daily.get('indicators', {}).get('rsi', {})
                    rsi_val_str = rsi_data.get('value')
                    if rsi_val_str:
                        rsi_value = float(rsi_val_str)
                        print(f"获取到 RSI(14): {rsi_value}")
                
                # 尝试获取价格数据
                try:
                    if 'props' in data and 'pageProps' in data['props']:
                        page_props = data['props']['pageProps']
                        if 'state' in page_props and 'etfStore' in page_props['state']:
                            etf_store = page_props['state']['etfStore']
                            if 'instrument' in etf_store and 'price' in etf_store['instrument']:
                                price_data = etf_store['instrument']['price']
                                if 'last' in price_data:
                                    latest_price = float(price_data['last'])
                                    print(f"获取到价格: {latest_price}")
                except Exception as e:
                    print(f"获取价格失败: {e}")

            except (json.JSONDecodeError, ValueError) as e:
                print(f"JSON解析错误: {e}")
        
        return rsi_value, latest_price

    except Exception as e:
        print(f"获取数据出错: {e}")
        return None, None

def send_email(to_email, subject, content):
    """
    发送邮件函数
    """
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("未配置发件人邮箱或密码，跳过发送邮件。")
        return

    message = MIMEText(content, 'plain', 'utf-8')
    message['From'] = Header("RSI 监控助手", 'utf-8')
    message['To'] = Header(to_email, 'utf-8')
    message['Subject'] = Header(subject, 'utf-8')

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, [to_email], message.as_string())
        server.quit()
        print(f"邮件已发送至 {to_email}")
    except Exception as e:
        print(f"邮件发送失败: {e}")

def send_wechat(title, content):
    """
    微信通知 (Server酱)
    """
    if not SERVERCHAN_KEY:
        print("未配置 SERVERCHAN_KEY，跳过微信通知。")
        return
    
    data = {'title': title,
            'desp': content,
            'channel': 9}
    msg_url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"

    try:
        response = requests.post(msg_url, data=data)
        print(f"微信通知发送结果: {response.text}")
    except Exception as e:
        print(f"微信通知发送失败: {e}")

def main():
    rsi, price = fetch_rsi_and_price()
    
    if rsi is None:
        print("未能获取有效 RSI 数据，程序结束。")
        return

    print(f"当前状态: RSI={rsi}, 价格={price}")

    subject = ""
    content = ""

    if rsi < RSI_BUY_THRESHOLD:
        subject = f"【买入提醒】红利低波ETF RSI低于{RSI_BUY_THRESHOLD}"
        content = f"当前红利低波ETF (512890) 的 14天 RSI 为 {rsi:.2f}，已低于 {RSI_BUY_THRESHOLD}，建议关注买入机会。\n当前价格: {price}"
    elif rsi > RSI_SELL_THRESHOLD:
        subject = f"【卖出提醒】红利低波ETF RSI高于{RSI_SELL_THRESHOLD}"
        content = f"当前红利低波ETF (512890) 的 14天 RSI 为 {rsi:.2f}，已高于 {RSI_SELL_THRESHOLD}，建议关注卖出风险。\n当前价格: {price}"
    else:
        print(f"RSI 在正常范围内 ({RSI_BUY_THRESHOLD}-{RSI_SELL_THRESHOLD})，无需发送提醒。")

    if subject:
        print(f"触发条件，准备发送邮件: {subject}")
        subscribers = [email.strip() for email in SUBSCRIBER_EMAILS if email.strip()]
        if not subscribers:
            print("没有配置订阅者邮箱 (SUBSCRIBER_EMAILS)，无法发送。")
        
        for email in subscribers:
            send_email(email, subject, content)
            
        # 发送微信通知
        send_wechat(subject, content)

    # ==========================================
    # 生成静态数据文件 (供 GitHub Pages 使用)
    # ==========================================
    public_dir = "public"
    if not os.path.exists(public_dir):
        os.makedirs(public_dir)
    
    # GitHub Actions 运行在 UTC 时区，需要转换为北京时间 (UTC+8)
    beijing_time = datetime.utcnow() + timedelta(hours=8)
    
    data = {
        "rsi": rsi,
        "price": price,
        "timestamp": beijing_time.strftime("%Y-%m-%d %H:%M:%S") + " (GitHub Actions)"
    }
    
    with open(os.path.join(public_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"静态数据已保存至 {public_dir}/data.json")

if __name__ == "__main__":
    main()
