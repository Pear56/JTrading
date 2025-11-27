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
# Server酱 Key
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY")
# Gist 订阅者列表配置
GIST_SUBSCRIBERS_URL = os.environ.get("GIST_SUBSCRIBERS_URL")
GIST_TOKEN = os.environ.get("GIST_TOKEN")

# ==========================================
# RSI 阈值配置
# ==========================================
RSI_BUY_THRESHOLD = int(os.environ.get("RSI_BUY_THRESHOLD", 40))
RSI_SELL_THRESHOLD = int(os.environ.get("RSI_SELL_THRESHOLD", 70))

def fetch_subscriber_emails():
    """
    从私有 Gist 获取订阅者邮箱列表
    如果 Gist 配置不存在，则回退到环境变量 SUBSCRIBER_EMAILS
    """
    # 优先从 Gist 读取
    if GIST_SUBSCRIBERS_URL and GIST_TOKEN:
        try:
            headers = {
                'Authorization': f'token {GIST_TOKEN}',
                'Accept': 'application/vnd.github.v3.raw'
            }
            response = requests.get(GIST_SUBSCRIBERS_URL, headers=headers, timeout=10)
            if response.status_code == 200:
                # 支持每行一个邮箱或逗号分隔
                content = response.text.strip()
                emails = []
                for line in content.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):  # 忽略空行和注释
                        # 支持逗号分隔的多个邮箱
                        emails.extend([e.strip() for e in line.split(',') if e.strip()])
                print(f"从 Gist 获取到 {len(emails)} 个订阅者邮箱")
                return emails
            else:
                print(f"从 Gist 获取邮箱失败: HTTP {response.status_code}")
        except Exception as e:
            print(f"从 Gist 获取邮箱出错: {e}")
    
    # 回退到环境变量
    fallback_emails = os.environ.get("SUBSCRIBER_EMAILS", "")
    if fallback_emails:
        emails = [e.strip() for e in fallback_emails.split(",") if e.strip()]
        print(f"使用环境变量 SUBSCRIBER_EMAILS，共 {len(emails)} 个订阅者")
        return emails
    
    return []

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

    # 构建 HTML 邮件内容
    html_content = f"""
    <html>
    <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f4f6f9; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 10px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.05);">
            <h2 style="color: #2c3e50; margin-top: 0; border-bottom: 2px solid #3498db; padding-bottom: 10px;">{subject}</h2>
            
            <div style="font-size: 16px; line-height: 1.6; color: #34495e; margin: 20px 0;">
                {content.replace(chr(10), '<br>')}
            </div>
            
            <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ecf0f1; font-size: 12px; color: #95a5a6; text-align: center;">
                <p>此邮件由 GitHub Actions 自动发送，请勿直接回复。</p>
                <p>
                    如果您不想继续接收此类邮件，可以 
                    <a href="mailto:{SENDER_EMAIL}?subject=取消订阅 RSI 监控&body=请将我的邮箱从订阅列表中移除" style="color: #e74c3c; text-decoration: none; font-weight: bold;">点击此处取消订阅</a>
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    message = MIMEText(html_content, 'html', 'utf-8')
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
        subscribers = fetch_subscriber_emails()
        if not subscribers:
            print("没有配置订阅者邮箱，无法发送。")
        
        for email in subscribers:
            send_email(email, subject, content)
            
        # 发送微信通知
        send_wechat(subject, content)

    # ==========================================
    # 生成静态数据文件 (供 GitHub Pages 使用)
    # ==========================================
    docs_dir = "docs"
    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir)
    
    # GitHub Actions 运行在 UTC 时区，需要转换为北京时间 (UTC+8)
    beijing_time = datetime.utcnow() + timedelta(hours=8)
    
    data = {
        "rsi": rsi,
        "price": price,
        "timestamp": beijing_time.strftime("%Y-%m-%d %H:%M:%S") + " (GitHub Actions)"
    }
    
    with open(os.path.join(docs_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"静态数据已保存至 {docs_dir}/data.json")

    # ==========================================
    # 动态注入 Formspree Endpoint (从环境变量)
    # ==========================================
    formspree_endpoint = os.environ.get("FORMSPREE_ENDPOINT")
    # 如果本地运行且未设置环境变量，可以使用默认值或保持占位符
    # 这里为了演示，如果未设置则不替换（前端会提交失败，或者你可以设置一个默认测试地址）
    
    if formspree_endpoint:
        index_path = os.path.join(docs_dir, "index.html")
        if os.path.exists(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                if "__FORMSPREE_ENDPOINT__" in content:
                    new_content = content.replace("__FORMSPREE_ENDPOINT__", formspree_endpoint)
                    with open(index_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    print(f"已将 index.html 中的 Formspree 地址更新为: {formspree_endpoint}")
                else:
                    print("index.html 中未找到 __FORMSPREE_ENDPOINT__ 占位符，跳过替换。")
            except Exception as e:
                print(f"更新 index.html 失败: {e}")

if __name__ == "__main__":
    main()
