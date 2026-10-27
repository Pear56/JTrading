"""
发送订阅确认邮件脚本
检测 Gist 中标记为 [pending] 的邮箱，发送确认邮件后移除标记
"""

import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import requests

# ==========================================
# 配置
# ==========================================
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.126.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")

# 订阅提示文案所使用的阈值（优先取环境变量，可与实时监控保持一致）
BUY_THRESHOLD = int(os.environ.get("CONFIRM_BUY_THRESHOLD", os.environ.get("RSI_BUY_THRESHOLD", 32)))
SELL_THRESHOLD = int(os.environ.get("CONFIRM_SELL_THRESHOLD", os.environ.get("RSI_SELL_THRESHOLD", 77)))

GIST_TOKEN = os.environ.get("GIST_TOKEN") or os.environ.get("GIST_TOKEN_WRITE")
GIST_ID = os.environ.get("GIST_ID")
GIST_FILENAME = os.environ.get("GIST_FILENAME") or "subscribers.txt"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
EMAIL_IN_TEXT_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_email(email):
    """日志用邮箱脱敏，不改变实际发送和 Gist 更新使用的原始邮箱。"""
    email = str(email or "").strip()
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain:
        return "***"
    visible = local[:3] if len(local) > 3 else local[:1]
    return f"{visible}***@{domain}"


def mask_text_emails(text):
    return EMAIL_IN_TEXT_PATTERN.sub(lambda match: mask_email(match.group(0)), str(text))


def parse_email_list(value):
    """解析一行里的邮箱，支持逗号、分号和空白分隔。"""
    emails = []
    seen = set()

    for candidate in re.split(r"[,;，；\s]+", value.strip()):
        email = candidate.strip()
        if not email:
            continue
        if not EMAIL_PATTERN.match(email):
            print(f"跳过无效邮箱: {mask_email(email)}")
            continue

        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        emails.append(email)

    return emails

# ==========================================
# Gist 操作
# ==========================================
def get_gist_content():
    """获取 Gist 内容"""
    if not GIST_ID or not GIST_TOKEN:
        print("GIST_ID 或 GIST_TOKEN 未配置")
        return None
    
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        'Authorization': f'token {GIST_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        return data['files'].get(GIST_FILENAME, {}).get('content', '')
    else:
        print(f"获取 Gist 失败: HTTP {response.status_code}")
        return None

def update_gist_content(new_content):
    """更新 Gist 内容"""
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        'Authorization': f'token {GIST_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "files": {
            GIST_FILENAME: {
                "content": new_content
            }
        }
    }
    
    response = requests.patch(url, headers=headers, json=payload, timeout=10)
    return response.status_code == 200

# ==========================================
# 邮件发送
# ==========================================
def build_confirmation_html(to_email):
    """构建与当前经典、动态双策略监控一致的订阅确认邮件。"""
    unsubscribe_email = SENDER_EMAIL
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }}
    .header {{ background: linear-gradient(135deg, #3498db 0%, #2980b9 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center; }}
    .content {{ background: #f9f9f9; padding: 30px; border: 1px solid #e0e0e0; }}
    .footer {{ background: #2c3e50; color: #bdc3c7; padding: 20px; border-radius: 0 0 10px 10px; text-align: center; font-size: 12px; }}
    .btn {{ display: inline-block; background: #3498db; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 10px 0; }}
    .unsubscribe {{ color: #95a5a6; text-decoration: none; }}
    h1 {{ margin: 0; font-size: 24px; }}
    .icon {{ font-size: 48px; margin-bottom: 10px; }}
    .strategy {{ background: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin: 14px 0; }}
    .strategy-title {{ font-weight: 700; margin-bottom: 8px; }}
  </style>
</head>
<body>
  <div class="header">
    <div class="icon">📈</div>
    <h1>订阅成功！</h1>
  </div>
  <div class="content">
    <p>您好！</p>
    <p>感谢您订阅 <strong>JTrading RSI 双策略监控</strong> 服务！</p>
    <p>从现在起，当 <strong>红利低波ETF (512890)</strong> 的经典策略或动态调优策略触发买卖信号时，您将收到邮件通知。</p>
    <div class="strategy">
      <div class="strategy-title">📊 经典固定阈值策略</div>
      <ul>
        <li>🟢 <strong>买入信号</strong>：RSI &lt; {BUY_THRESHOLD}</li>
        <li>🔴 <strong>卖出信号</strong>：RSI &gt; {SELL_THRESHOLD}</li>
      </ul>
    </div>
    <div class="strategy">
      <div class="strategy-title">⚡ RSI + 波动率动态调优策略</div>
      <p>系统会读取每周最新优化参数，并结合当日年化波动率计算动态买入和卖出阈值。</p>
      <p>动态策略提醒会列出当日 RSI、实时动态阈值和波动率，方便您核对触发原因。</p>
    </div>
    <p style="text-align: center;">
      <a href="https://pear56.github.io/JTrading/" class="btn">查看实时监控面板</a>
    </p>
    <p style="color: #7f8c8d; font-size: 14px;">
      <em>提示：RSI 仅作为参考指标，投资需谨慎，建议结合其他分析方法。</em>
    </p>
  </div>
  <div class="footer">
    <p>JTrading - RSI 智能监控服务</p>
    <p>如需取消订阅，请<a href="mailto:{unsubscribe_email}?subject=取消订阅 JTrading&body=请取消此邮箱的订阅：{to_email}" class="unsubscribe">点击这里</a></p>
  </div>
</body>
</html>
    """.strip()


def send_confirmation_email(to_email):
    """发送订阅确认邮件"""
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("邮件发送配置不完整")
        return False

    html_content = build_confirmation_html(to_email)

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = f"JTrading <{SENDER_EMAIL}>"
        msg['To'] = to_email
        msg['Subject'] = Header("✅ 订阅成功 - JTrading RSI 双策略监控", 'utf-8')
        
        # 添加 HTML 内容
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        # 发送邮件
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())
        
        print(f"确认邮件已发送至: {mask_email(to_email)}")
        return True
    except Exception as e:
        print(f"发送邮件失败 ({mask_email(to_email)}): {mask_text_emails(e)}")
        return False

# ==========================================
# 主逻辑
# ==========================================
def main():
    print("检查待发送确认邮件的订阅者...")
    
    content = get_gist_content()
    if content is None:
        print("无法获取 Gist 内容")
        return
    
    lines = content.splitlines()
    pending_emails = []
    line_items = []
    
    # 查找 [pending] 标记的邮箱
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            line_items.append(("literal", line))
            continue
        
        # 匹配 [pending] email@xxx.com
        match = re.match(r'^\[pending\]\s*(.+)$', line, re.IGNORECASE)
        if match:
            emails = parse_email_list(match.group(1))
            for email in emails:
                pending_emails.append(email)
                line_items.append(("pending", email))
        else:
            line_items.append(("literal", line))
    
    if not pending_emails:
        print("没有待发送确认邮件的订阅者")
        return
    
    print(f"发现 {len(pending_emails)} 个待确认的订阅者")
    
    # 发送确认邮件
    success_emails = set()
    for email in pending_emails:
        if send_confirmation_email(email):
            success_emails.add(email.lower())

    success_count = len(success_emails)
    
    # 更新 Gist：只移除发送成功邮箱的 [pending] 标记，失败的保留下次重试。
    if success_count > 0:
        new_lines = []
        for item_type, value in line_items:
            if item_type == "pending":
                if value.lower() in success_emails:
                    new_lines.append(value)
                else:
                    new_lines.append(f"[pending] {value}")
            else:
                new_lines.append(value)

        new_content = '\n'.join(new_lines)
        if update_gist_content(new_content):
            print(f"Gist 已更新，{success_count} 个邮箱已确认")
        else:
            print("警告: Gist 更新失败")
    
    print(f"完成：发送了 {success_count}/{len(pending_emails)} 封确认邮件")

if __name__ == "__main__":
    main()
