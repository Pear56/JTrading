import os
import json
import re
import smtplib
import time
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from html import escape
from datetime import datetime, timedelta
import requests
import pandas as pd
import numpy as np

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
GIST_TOKEN = os.environ.get("GIST_TOKEN") or os.environ.get("GIST_TOKEN_READ") or os.environ.get("GIST_TOKEN_WRITE")
GIST_ID = os.environ.get("GIST_ID")
GIST_FILENAME = os.environ.get("GIST_FILENAME") or "subscribers.txt"
EMAIL_SEND_DELAY_SECONDS = float(os.environ.get("EMAIL_SEND_DELAY_SECONDS", os.environ.get("EMAIL_BATCH_DELAY_SECONDS", 2)))
PROJECT_URL = os.environ.get("PROJECT_URL", "https://pear56.github.io/JTrading").strip() or "https://pear56.github.io/JTrading"

# ==========================================
# 最优策略参数配置 (来自回测优化结果)
# RSI(15) EMA 32/77 - 联结基金模式（理论最优）
# 总收益268.02%, 年化20.90%
# 注：联结基金可小数份额申购，ETF需100份整手交易
# ==========================================
ETF_CODE = "512890"  # 红利低波ETF
ETF_NAME = "红利低波ETF"
RSI_PERIOD = 15  # RSI周期（使用EMA平滑）
RSI_BUY_THRESHOLD = int(os.environ.get("RSI_BUY_THRESHOLD", 32))  # 买入阈值
RSI_SELL_THRESHOLD = int(os.environ.get("RSI_SELL_THRESHOLD", 77))  # 卖出阈值
DATA_FETCH_RETRIES = int(os.environ.get("DATA_FETCH_RETRIES", 3))
DATA_FETCH_TIMEOUT = int(os.environ.get("DATA_FETCH_TIMEOUT", 20))

BEST_PARAMS_PATH = os.path.join("backtest", "best_combined_params.json")
BACKTEST_RESULT_PATH = os.path.join("backtest", "backtest_result.json")

DATA_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://quote.eastmoney.com/",
}

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
EMAIL_IN_TEXT_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_email(email):
    """日志用邮箱脱敏，不改变实际发送和存储使用的原始邮箱。"""
    email = str(email or "").strip()
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain:
        return "***"
    visible = local[:3] if len(local) > 3 else local[:1]
    return f"{visible}***@{domain}"


def mask_email_list(emails):
    return ", ".join(mask_email(email) for email in emails)


def mask_text_emails(text):
    return EMAIL_IN_TEXT_PATTERN.sub(lambda match: mask_email(match.group(0)), str(text))


def load_json_file(file_path):
    """安全读取 JSON 文件。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"读取 {file_path} 失败: {e}")
        return None


def load_backtest_summary():
    """读取回测统计摘要，避免前端展示过期硬编码收益。"""
    data = load_json_file(BACKTEST_RESULT_PATH)
    stats = (data or {}).get("statistics", {})
    strategy_ideal = stats.get("strategy_ideal") or stats.get("strategy") or {}
    strategy_dynamic = stats.get("strategy_dynamic") or {}
    return {
        "classic_total": strategy_ideal.get("total_return"),
        "classic_annual": strategy_ideal.get("annual_return"),
        "dynamic_total": strategy_dynamic.get("total_return"),
        "dynamic_annual": strategy_dynamic.get("annual_return"),
    }


def format_percent(value):
    number = format_number(value, 2)
    return f"{number}%" if number != "--" else "--"


def format_number(value, digits=2):
    if value is None:
        return "--"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "--"


def load_dynamic_params():
    """读取动态策略最优参数；若缺失则回退到保守默认值。"""
    params = load_json_file(BEST_PARAMS_PATH) or {}
    return {
        "rsi_period": int(params.get("rsi_period", RSI_PERIOD)),
        "rsi_buy_base": float(params.get("rsi_buy_base", 34)),
        "rsi_sell_base": float(params.get("rsi_sell_base", 72)),
        "vol_window": int(params.get("vol_window", 20)),
        "k_vol": float(params.get("k_vol", 0.0)),
        "vol_anchor": float(params.get("vol_anchor", 15.0)),
    }


def calculate_volatility_annualized(close_series, window):
    """按回测口径计算年化波动率(%)。"""
    if close_series is None or len(close_series) < window + 1:
        return None

    log_ret = np.log(close_series / close_series.shift(1))
    vol = log_ret.rolling(window=window).std() * np.sqrt(252) * 100
    latest = vol.iloc[-1]
    if pd.isna(latest):
        return None
    return float(latest)


def compute_dynamic_signal(rsi_value, close_series, params):
    """基于 RSI + 波动率参数计算当日动态阈值与信号。"""
    vol = calculate_volatility_annualized(close_series, params["vol_window"])
    if vol is None or rsi_value is None:
        return None

    adjustment = params["k_vol"] * (vol - params["vol_anchor"])
    buy_threshold = params["rsi_buy_base"] - adjustment
    sell_threshold = params["rsi_sell_base"] + adjustment

    # 与回测前端保持一致的阈值边界
    buy_threshold = min(50.0, max(20.0, buy_threshold))
    sell_threshold = min(90.0, max(60.0, sell_threshold))

    if rsi_value < buy_threshold:
        signal = "买入"
        signal_color = "#22c55e"
    elif rsi_value > sell_threshold:
        signal = "卖出"
        signal_color = "#ef4444"
    else:
        signal = "持有"
        signal_color = "#3b82f6"

    return {
        "volatility": round(vol, 2),
        "buy_threshold": round(buy_threshold, 2),
        "sell_threshold": round(sell_threshold, 2),
        "signal": signal,
        "signal_color": signal_color,
    }


def build_trade_alert(
    action,
    rsi,
    price,
    market_date,
    period,
    buy_threshold,
    sell_threshold,
    backtest_return,
    backtest_annual,
    strategy_name,
    subject_prefix="",
    volatility=None,
    threshold_digits=2,
):
    """按策略构建一封买卖提醒；持有状态不应调用此函数。"""
    is_buy = action == "买入"
    threshold = buy_threshold if is_buy else sell_threshold
    direction = "低于" if is_buy else "高于"
    suggestion = "建议关注买入机会" if is_buy else "建议关注卖出风险"
    subject = (
        f"【{subject_prefix}{action}提醒】{ETF_NAME} "
        f"RSI{direction}{format_number(threshold, threshold_digits)}"
    )

    volatility_line = ""
    if volatility is not None:
        volatility_line = f"\n- 当前年化波动率: {format_number(volatility, 2)}%"

    content = f"""当前{ETF_NAME} ({ETF_CODE}) 的 RSI({period}) EMA 为 {rsi:.2f}，已{direction} {format_number(threshold, threshold_digits)}，{suggestion}。

📊 {strategy_name}参数:
- RSI周期: {period}日 (EMA平滑)
- 买入阈值: RSI < {format_number(buy_threshold, threshold_digits)}
- 卖出阈值: RSI > {format_number(sell_threshold, threshold_digits)}{volatility_line}

💰 回测表现:
- 总收益: {backtest_return}
- 年化收益: {backtest_annual}

当前价格: {price}
项目网页: {PROJECT_URL}"""

    return {
        "subject": subject,
        "content": content,
        "context": {
            "action": action,
            "strategy_name": strategy_name,
            "rsi": rsi,
            "price": price,
            "market_date": market_date,
            "period": period,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "threshold_digits": threshold_digits,
            "volatility": volatility,
            "backtest_return": backtest_return,
            "backtest_annual": backtest_annual,
        },
    }

def parse_subscriber_emails(content, include_pending=False):
    """解析订阅者邮箱，支持换行、逗号/分号分隔和 [pending]/[confirmed] 标记。"""
    emails = []
    seen = set()

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        status_match = re.match(r"^\[(pending|confirmed)\]\s*(.+)$", line, re.IGNORECASE)
        if status_match:
            status = status_match.group(1).lower()
            line = status_match.group(2).strip()
            if status == "pending" and not include_pending:
                continue

        for candidate in re.split(r"[,;，；\s]+", line):
            email = candidate.strip()
            if not email:
                continue
            if not EMAIL_PATTERN.match(email):
                print(f"跳过无效订阅邮箱: {mask_email(email)}")
                continue

            key = email.lower()
            if key in seen:
                continue

            seen.add(key)
            emails.append(email)

    return emails


def summarize_subscriber_content(content):
    """统计订阅文件中的邮箱状态，帮助排查 Gist 配置或确认流程问题。"""
    counts = {
        "confirmed": 0,
        "pending": 0,
        "invalid": 0,
        "duplicates": 0,
    }
    seen = set()

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        status = "confirmed"
        status_match = re.match(r"^\[(pending|confirmed)\]\s*(.+)$", line, re.IGNORECASE)
        if status_match:
            status = status_match.group(1).lower()
            line = status_match.group(2).strip()

        for candidate in re.split(r"[,;，；\s]+", line):
            email = candidate.strip()
            if not email:
                continue
            if not EMAIL_PATTERN.match(email):
                counts["invalid"] += 1
                continue

            key = email.lower()
            if key in seen:
                counts["duplicates"] += 1
                continue

            seen.add(key)
            counts["pending" if status == "pending" else "confirmed"] += 1

    counts["total_unique"] = counts["confirmed"] + counts["pending"]
    return counts


def fetch_gist_subscriber_content():
    """优先通过 Gist API 读取当前订阅文件；raw URL 仅作为兜底。"""
    if not GIST_TOKEN:
        return None

    headers_raw = {
        'Authorization': f'token {GIST_TOKEN}',
        'Accept': 'application/vnd.github.v3.raw'
    }
    headers_json = {
        'Authorization': f'token {GIST_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }

    if GIST_ID:
        try:
            url = f"https://api.github.com/gists/{GIST_ID}"
            response = requests.get(url, headers=headers_json, timeout=10)
            if response.status_code == 200:
                gist = response.json()
                file_info = gist.get("files", {}).get(GIST_FILENAME)
                if not file_info:
                    print(f"Gist 中找不到订阅文件: {GIST_FILENAME}")
                    return None
                print(f"通过 Gist API 读取订阅文件: {GIST_FILENAME}")
                return file_info.get("content", "")
            print(f"从 Gist API 获取邮箱失败: HTTP {response.status_code}")
        except Exception as e:
            print(f"从 Gist API 获取邮箱出错: {e}")

    if GIST_SUBSCRIBERS_URL:
        try:
            response = requests.get(GIST_SUBSCRIBERS_URL, headers=headers_raw, timeout=10)
            if response.status_code == 200:
                print("通过 GIST_SUBSCRIBERS_URL 读取订阅文件")
                return response.text
            print(f"从 Gist raw URL 获取邮箱失败: HTTP {response.status_code}")
        except Exception as e:
            print(f"从 Gist raw URL 获取邮箱出错: {e}")

    return None


def fetch_subscriber_emails():
    """
    从私有 Gist 获取订阅者邮箱列表。
    如果 Gist 配置不存在或读取失败，则回退到环境变量 SUBSCRIBER_EMAILS。
    """
    content = fetch_gist_subscriber_content()
    if content is not None:
        emails = parse_subscriber_emails(content)
        summary = summarize_subscriber_content(content)
        print(
            "订阅文件统计: "
            f"confirmed={summary['confirmed']}, "
            f"pending={summary['pending']}, "
            f"invalid={summary['invalid']}, "
            f"duplicates={summary['duplicates']}, "
            f"total_unique={summary['total_unique']}"
        )
        print(f"从 Gist 获取到 {len(emails)} 个已确认订阅者邮箱")
        return emails

    fallback_emails = os.environ.get("SUBSCRIBER_EMAILS", "")
    if fallback_emails:
        emails = parse_subscriber_emails(fallback_emails)
        print(f"使用环境变量 SUBSCRIBER_EMAILS，共 {len(emails)} 个订阅者")
        return emails

    return []

def calculate_rsi_ema(prices, period):
    """
    计算RSI指标（使用EMA平滑，更敏感）
    与回测代码保持一致
    """
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    
    # 使用EMA而非SMA（更敏感）
    alpha = 1 / period  # EMA平滑因子
    avg_gain = gain.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def normalize_etf_history(df, source_name, days):
    """统一不同数据源的字段，并做基础清洗。"""
    if df is None or df.empty:
        raise ValueError(f"{source_name} 返回空数据")

    column_map = {}
    if "日期" in df.columns:
        column_map["日期"] = "date"
    if "收盘" in df.columns:
        column_map["收盘"] = "close"
    df = df.rename(columns=column_map)

    missing_columns = {"date", "close"} - set(df.columns)
    if missing_columns:
        raise ValueError(f"{source_name} 缺少字段: {', '.join(sorted(missing_columns))}")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"])
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

    if df.empty:
        raise ValueError(f"{source_name} 清洗后无有效数据")

    df = df.tail(days).reset_index(drop=True)
    start_date = df["date"].min().strftime("%Y-%m-%d")
    end_date = df["date"].max().strftime("%Y-%m-%d")
    print(f"{source_name} 获取到 {len(df)} 条数据，从 {start_date} 到 {end_date}")
    return df


def fetch_etf_data_from_akshare(code, days):
    """使用 AKShare 获取 ETF 前复权日线数据。"""
    import akshare as ak

    df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
    return normalize_etf_history(df, "AKShare", days)


def get_eastmoney_secids(code):
    """生成东方财富 secid，ETF 512/510 等上海代码通常为 1.x。"""
    preferred_market = "1" if code.startswith(("5", "6", "9")) else "0"
    fallback_market = "0" if preferred_market == "1" else "1"
    return [f"{preferred_market}.{code}", f"{fallback_market}.{code}"]


def fetch_etf_data_from_eastmoney(code, days):
    """直接调用东方财富 K 线接口，作为 AKShare 被断连时的备用数据源。"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    last_error = None
    session = requests.Session()
    session.trust_env = False

    for secid in get_eastmoney_secids(code):
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",  # 前复权
            "beg": "0",
            "end": "20500101",
        }
        try:
            response = session.get(
                url,
                params=params,
                headers=DATA_REQUEST_HEADERS,
                timeout=DATA_FETCH_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            klines = (payload.get("data") or {}).get("klines") or []
            if not klines:
                raise ValueError(f"东方财富 {secid} 无 K 线数据")

            rows = []
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 3:
                    rows.append({"date": parts[0], "close": parts[2]})

            return normalize_etf_history(pd.DataFrame(rows), f"东方财富({secid})", days)
        except Exception as e:
            last_error = e
            print(f"东方财富 {secid} 获取失败: {e}")

    raise RuntimeError(f"东方财富备用数据源不可用: {last_error}")


def get_sina_symbol(code):
    """生成新浪行情 symbol，上海 ETF 使用 sh 前缀。"""
    market_prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return f"{market_prefix}{code}"


def fetch_etf_data_from_sina(code, days):
    """调用新浪日线接口，作为行情源被断开时的第二备用数据源。"""
    url = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20data=/CN_MarketDataService.getKLineData"
    symbol = get_sina_symbol(code)
    session = requests.Session()
    session.trust_env = False

    response = session.get(
        url,
        params={
            "symbol": symbol,
            "scale": "240",
            "ma": "no",
            "datalen": str(max(days, RSI_PERIOD + 5)),
        },
        headers=DATA_REQUEST_HEADERS,
        timeout=DATA_FETCH_TIMEOUT,
    )
    response.raise_for_status()

    text = response.text
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("新浪返回内容不是有效的 JSONP K 线数据")

    rows = [
        {"date": item.get("day"), "close": item.get("close")}
        for item in json.loads(text[start : end + 1])
    ]
    return normalize_etf_history(pd.DataFrame(rows), f"新浪({symbol})", days)


def fetch_with_retries(source_name, fetcher):
    """对容易被 GitHub Actions 网络波动影响的数据源做短重试。"""
    last_error = None
    retries = max(1, DATA_FETCH_RETRIES)

    for attempt in range(1, retries + 1):
        try:
            return fetcher()
        except Exception as e:
            last_error = e
            print(f"{source_name} 第 {attempt}/{retries} 次获取失败: {e}")
            if attempt < retries:
                time.sleep(min(2 * attempt, 8))

    print(f"{source_name} 多次获取失败，准备切换数据源: {last_error}")
    return None


def fetch_etf_data(code, days=60):
    """
    获取ETF历史数据。
    优先使用 AKShare；若 GitHub Actions 网络被对端断开，则回退到东方财富直连接口。
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始获取 {code} 数据...")

    data_sources = [
        ("AKShare", lambda: fetch_etf_data_from_akshare(code, days)),
        ("东方财富备用接口", lambda: fetch_etf_data_from_eastmoney(code, days)),
        ("新浪备用接口", lambda: fetch_etf_data_from_sina(code, days)),
    ]

    for source_name, fetcher in data_sources:
        df = fetch_with_retries(source_name, fetcher)
        if df is not None:
            return df

    print("获取ETF数据失败: 所有数据源均不可用")
    return None


def fetch_rsi_and_price():
    """
    获取 RSI 和 价格数据
    使用自己计算的 RSI(15) EMA，与回测策略保持一致
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始获取数据...")
    
    # 获取ETF历史数据
    df = fetch_etf_data(ETF_CODE, days=60)  # 获取60天数据，确保RSI计算准确
    
    if df is None or len(df) < RSI_PERIOD + 5:
        print("无法获取足够的历史数据")
        return None, None, None, None
    
    # 计算RSI(15) EMA
    df['rsi'] = calculate_rsi_ema(df['close'], RSI_PERIOD)
    
    # 获取最新的RSI和价格
    latest = df.iloc[-1]
    rsi_value = latest['rsi']
    latest_price = latest['close']
    latest_date = latest['date'].strftime('%Y-%m-%d')
    
    if pd.notna(rsi_value):
        print(f"获取到 RSI({RSI_PERIOD}) EMA: {rsi_value:.2f}")
        print(f"最新价格: {latest_price:.4f}")
        print(f"数据日期: {latest_date}")
    else:
        print("RSI计算失败，数据不足")
        return None, None, None, None
    
    return rsi_value, latest_price, latest_date, df

def render_multiline_html(content):
    """将文本内容转换为邮件安全的 HTML 段落。"""
    blocks = []
    for block in str(content or "").strip().split("\n\n"):
        lines = [escape(line.strip()) for line in block.splitlines() if line.strip()]
        if lines:
            blocks.append(
                '<p style="margin: 0 0 14px; font-size: 15px; line-height: 1.7; color: #374151;">'
                + "<br>".join(lines)
                + "</p>"
            )
    return "".join(blocks) or '<p style="margin: 0; color: #6b7280;">暂无详情。</p>'


def build_alert_message(to_header, subject, content, alert_context=None):
    """构建 RSI 提醒邮件。"""
    alert_context = alert_context or {}
    action = alert_context.get("action")
    is_trade_alert = action in ("买入", "卖出")

    if is_trade_alert:
        is_buy = action == "买入"
        strategy_name = escape(str(alert_context.get("strategy_name") or "经典回测策略"))
        accent = "#16a34a" if is_buy else "#dc2626"
        accent_dark = "#166534" if is_buy else "#991b1b"
        accent_bg = "#ecfdf3" if is_buy else "#fef2f2"
        headline = "RSI 进入买入关注区" if is_buy else "RSI 进入卖出风险区"
        direction = "低于买入阈值" if is_buy else "高于卖出阈值"
        threshold_value = alert_context.get("buy_threshold") if is_buy else alert_context.get("sell_threshold")
        threshold_label = "买入阈值" if is_buy else "卖出阈值"
        rsi_text = format_number(alert_context.get("rsi"), 2)
        price_text = format_number(alert_context.get("price"), 4)
        period_text = escape(str(alert_context.get("period") or RSI_PERIOD))
        market_date = escape(str(alert_context.get("market_date") or "--"))
        threshold_digits = int(alert_context.get("threshold_digits", 2))
        buy_threshold = format_number(alert_context.get("buy_threshold"), threshold_digits)
        sell_threshold = format_number(alert_context.get("sell_threshold"), threshold_digits)
        threshold_text = format_number(threshold_value, threshold_digits)
        volatility = alert_context.get("volatility")
        volatility_html = ""
        if volatility is not None:
            volatility_html = (
                '<p style="margin: 0 0 6px; font-size: 14px; line-height: 1.6; color: #4b5563;">'
                f"当前年化波动率：{format_number(volatility, 2)}%</p>"
            )
        backtest_return = escape(str(alert_context.get("backtest_return") or "--"))
        backtest_annual = escape(str(alert_context.get("backtest_annual") or "--"))
        page_url = escape(PROJECT_URL, quote=True)
        preheader = escape(f"{ETF_NAME} {ETF_CODE} {action}提醒，RSI {rsi_text}，请查看实时面板。")
        summary = (
            f"当前 {escape(ETF_NAME)} ({escape(ETF_CODE)}) 的 RSI({period_text}) EMA 为 "
            f"<strong style=\"color: {accent_dark};\">{rsi_text}</strong>，已{direction} "
            f"<strong>{threshold_text}</strong>。"
        )
        body_html = f"""
            <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">{preheader}</div>
            <div style="background: {accent_bg}; border: 1px solid {accent}; border-radius: 8px; padding: 14px 16px; margin-bottom: 20px;">
                <div style="font-size: 13px; font-weight: 700; color: {accent_dark}; margin-bottom: 8px;">{strategy_name} · {action}提醒</div>
                <h1 style="margin: 0 0 8px; font-size: 24px; line-height: 1.3; color: #111827;">{headline}</h1>
                <p style="margin: 0; font-size: 15px; line-height: 1.7; color: #374151;">{summary}</p>
            </div>

            <div style="text-align: center; margin: 24px 0;">
                <a href="{page_url}" style="display: inline-block; background: {accent}; color: #ffffff; text-decoration: none; font-size: 15px; font-weight: 700; padding: 12px 24px; border-radius: 6px;">查看项目网页</a>
            </div>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse; margin: 0 0 22px;">
                <tr>
                    <td style="width: 50%; padding: 10px; border: 1px solid #e5e7eb; border-radius: 8px 0 0 0;">
                        <div style="font-size: 12px; color: #6b7280;">RSI({period_text}) EMA</div>
                        <div style="font-size: 22px; font-weight: 800; color: #111827; margin-top: 4px;">{rsi_text}</div>
                    </td>
                    <td style="width: 50%; padding: 10px; border: 1px solid #e5e7eb; border-left: 0; border-radius: 0 8px 0 0;">
                        <div style="font-size: 12px; color: #6b7280;">最新价格</div>
                        <div style="font-size: 22px; font-weight: 800; color: #111827; margin-top: 4px;">{price_text}</div>
                    </td>
                </tr>
                <tr>
                    <td style="width: 50%; padding: 10px; border: 1px solid #e5e7eb; border-top: 0; border-radius: 0 0 0 8px;">
                        <div style="font-size: 12px; color: #6b7280;">买入阈值</div>
                        <div style="font-size: 18px; font-weight: 700; color: #166534; margin-top: 4px;">RSI &lt; {buy_threshold}</div>
                    </td>
                    <td style="width: 50%; padding: 10px; border: 1px solid #e5e7eb; border-left: 0; border-top: 0; border-radius: 0 0 8px 0;">
                        <div style="font-size: 12px; color: #6b7280;">卖出阈值</div>
                        <div style="font-size: 18px; font-weight: 700; color: #991b1b; margin-top: 4px;">RSI &gt; {sell_threshold}</div>
                    </td>
                </tr>
            </table>

            <div style="background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 16px; margin-bottom: 20px;">
                <div style="font-size: 13px; font-weight: 700; color: #374151; margin-bottom: 8px;">{strategy_name}参考</div>
                <p style="margin: 0 0 6px; font-size: 14px; line-height: 1.6; color: #4b5563;">触发条件：{threshold_label}，{direction}。</p>
                {volatility_html}
                <p style="margin: 0 0 6px; font-size: 14px; line-height: 1.6; color: #4b5563;">数据日期：{market_date}</p>
                <p style="margin: 0; font-size: 14px; line-height: 1.6; color: #4b5563;">回测表现：总收益 {backtest_return}，年化 {backtest_annual}</p>
            </div>

            <p style="margin: 0; font-size: 13px; line-height: 1.7; color: #6b7280;">提示：RSI 仅作为参考指标，投资需谨慎，建议结合仓位、估值和市场环境综合判断。</p>
        """
    else:
        page_url = escape(PROJECT_URL, quote=True)
        subject_html = escape(subject)
        body_html = f"""
            <h1 style="margin: 0 0 16px; font-size: 22px; line-height: 1.3; color: #111827;">{subject_html}</h1>
            {render_multiline_html(content)}
            <div style="text-align: center; margin: 24px 0;">
                <a href="{page_url}" style="display: inline-block; background: #2563eb; color: #ffffff; text-decoration: none; font-size: 15px; font-weight: 700; padding: 12px 24px; border-radius: 6px;">查看项目网页</a>
            </div>
        """

    unsubscribe_email = escape(SENDER_EMAIL or "", quote=True)
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin: 0; padding: 0; background-color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse; background-color: #f3f4f6;">
            <tr>
                <td style="padding: 24px 12px;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width: 640px; margin: 0 auto; border-collapse: collapse;">
                        <tr>
                            <td style="background: #111827; color: #ffffff; padding: 18px 22px; border-radius: 8px 8px 0 0;">
                                <div style="font-size: 18px; font-weight: 800; letter-spacing: 0;">JTrading RSI 监控</div>
                                <div style="font-size: 13px; color: #d1d5db; margin-top: 4px;">{escape(ETF_NAME)} · {escape(ETF_CODE)}</div>
                            </td>
                        </tr>
                        <tr>
                            <td style="background: #ffffff; padding: 24px 22px; border: 1px solid #e5e7eb; border-top: 0;">
                                {body_html}
                            </td>
                        </tr>
                        <tr>
                            <td style="background: #ffffff; padding: 16px 22px 22px; border: 1px solid #e5e7eb; border-top: 0; border-radius: 0 0 8px 8px; text-align: center;">
                                <p style="margin: 0 0 8px; font-size: 12px; line-height: 1.6; color: #9ca3af;">此邮件由 GitHub Actions 自动发送，请勿直接回复。</p>
                                <p style="margin: 0; font-size: 12px; line-height: 1.6; color: #9ca3af;">
                                    网页无法打开按钮时，可直接访问：
                                    <a href="{escape(PROJECT_URL, quote=True)}" style="color: #2563eb; text-decoration: none;">{escape(PROJECT_URL)}</a>
                                </p>
                                <p style="margin: 8px 0 0; font-size: 12px; line-height: 1.6; color: #9ca3af;">
                                    如需取消订阅，可
                                    <a href="mailto:{unsubscribe_email}?subject=取消订阅 RSI 监控&body=请将我的邮箱从订阅列表中移除" style="color: #dc2626; text-decoration: none; font-weight: 700;">点击此处取消订阅</a>
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    message = MIMEText(html_content, 'html', 'utf-8')
    # 只编码显示名，邮箱地址保持 RFC5322 可解析的 addr-spec。
    message['From'] = formataddr(("RSI 监控助手", SENDER_EMAIL), charset='utf-8')
    message['To'] = to_header
    message['Subject'] = Header(subject, 'utf-8')
    return message


def send_email(to_email, subject, content, alert_context=None):
    """发送单个收件人的提醒邮件，保留给临时测试或手动调用。"""
    return send_email_batch([to_email], subject, content, alert_context)


def send_email_batch(to_emails, subject, content, alert_context=None):
    """逐个收件人单独发送提醒邮件，避免 BCC 批量投递被邮箱服务商丢弃。"""
    recipients = [email.strip() for email in to_emails if email and email.strip()]
    if not recipients:
        return 0

    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("未配置发件人邮箱或密码，跳过发送邮件。")
        return 0

    sent_count = 0
    total = len(recipients)
    for index, email in enumerate(recipients, start=1):
        message = build_alert_message(email, subject, content, alert_context)

        try:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                refused = server.sendmail(SENDER_EMAIL, [email], message.as_string())

            if refused:
                print(f"第 {index}/{total} 封邮件被 SMTP 拒绝: {mask_email(email)}")
            else:
                sent_count += 1
                print(f"第 {index}/{total} 封邮件发送成功: {mask_email(email)}")
        except Exception as e:
            print(f"第 {index}/{total} 封邮件发送失败 ({mask_email(email)}): {mask_text_emails(e)}")

        if index < total and EMAIL_SEND_DELAY_SECONDS > 0:
            time.sleep(EMAIL_SEND_DELAY_SECONDS)

    print(f"邮件逐封发送完成: {sent_count}/{total}")
    return sent_count


def send_email_batches(subscribers, subject, content, alert_context=None):
    """向订阅者逐封发送提醒邮件。"""
    if not subscribers:
        return 0

    print(f"准备逐封发送提醒邮件，共 {len(subscribers)} 个收件人")
    return send_email_batch(subscribers, subject, content, alert_context)

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
    rsi, price, latest_date, market_df = fetch_rsi_and_price()
    
    if rsi is None:
        print("未能获取有效 RSI 数据，程序结束。")
        raise SystemExit(1)

    print(f"当前状态: RSI={rsi}, 价格={price}")

    backtest_summary = load_backtest_summary()
    classic_return = format_percent(backtest_summary["classic_total"])
    classic_annual = format_percent(backtest_summary["classic_annual"])
    dynamic_return = format_percent(backtest_summary["dynamic_total"])
    dynamic_annual = format_percent(backtest_summary["dynamic_annual"])
    dynamic_params = load_dynamic_params()
    close_series = market_df["close"] if market_df is not None else None
    dynamic_rsi = rsi
    if close_series is not None and dynamic_params["rsi_period"] != RSI_PERIOD:
        dynamic_rsi_series = calculate_rsi_ema(close_series, dynamic_params["rsi_period"])
        latest_dynamic_rsi = dynamic_rsi_series.iloc[-1]
        dynamic_rsi = float(latest_dynamic_rsi) if pd.notna(latest_dynamic_rsi) else None
    dynamic_signal = compute_dynamic_signal(dynamic_rsi, close_series, dynamic_params)
    alerts = []

    if rsi < RSI_BUY_THRESHOLD:
        classic_signal = "买入"
    elif rsi > RSI_SELL_THRESHOLD:
        classic_signal = "卖出"
    else:
        classic_signal = "持有"
        print(f"RSI 在正常范围内 ({RSI_BUY_THRESHOLD}-{RSI_SELL_THRESHOLD})，无需发送提醒。")

    if classic_signal in ("买入", "卖出"):
        alerts.append(build_trade_alert(
            classic_signal, rsi, price, latest_date, RSI_PERIOD,
            RSI_BUY_THRESHOLD, RSI_SELL_THRESHOLD,
            classic_return, classic_annual, "经典回测策略",
            threshold_digits=0,
        ))

    if dynamic_signal and dynamic_signal["signal"] in ("买入", "卖出"):
        alerts.append(build_trade_alert(
            dynamic_signal["signal"], dynamic_rsi, price, latest_date, dynamic_params["rsi_period"],
            dynamic_signal["buy_threshold"], dynamic_signal["sell_threshold"],
            dynamic_return, dynamic_annual, "动态调优策略",
            subject_prefix="动态调优", volatility=dynamic_signal["volatility"],
        ))
    elif dynamic_signal:
        print(
            f"动态调优 RSI 在正常范围内 "
            f"({dynamic_signal['buy_threshold']}-{dynamic_signal['sell_threshold']})，无需发送提醒。"
        )
    else:
        print("动态调优信号计算失败，跳过动态提醒。")

    if alerts:
        subscribers = fetch_subscriber_emails()
        if not subscribers:
            print("没有配置订阅者邮箱，无法发送。")

        for alert in alerts:
            print(f"触发条件，准备发送邮件: {alert['subject']}")
            send_email_batches(subscribers, alert["subject"], alert["content"], alert["context"])

            print(f"触发条件，准备发送微信通知: {alert['subject']}")
            send_wechat(alert["subject"], alert["content"])

    # ==========================================
    # 生成静态数据文件 (供 GitHub Pages 使用)
    # ==========================================
    docs_dir = "docs"
    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir)
    
    # GitHub Actions 运行在 UTC 时区，需要转换为北京时间 (UTC+8)
    beijing_time = datetime.utcnow() + timedelta(hours=8)
    
    # 计算买卖信号状态
    if rsi < RSI_BUY_THRESHOLD:
        signal = "买入"
        signal_color = "#22c55e"  # 绿色
    elif rsi > RSI_SELL_THRESHOLD:
        signal = "卖出"
        signal_color = "#ef4444"  # 红色
    else:
        signal = "持有"
        signal_color = "#3b82f6"  # 蓝色
    
    data = {
        "etf_code": ETF_CODE,
        "etf_name": ETF_NAME,
        "rsi": round(rsi, 2),
        "rsi_period": RSI_PERIOD,
        "market_date": latest_date,
        "price": round(price, 4) if price else None,
        "buy_threshold": RSI_BUY_THRESHOLD,
        "sell_threshold": RSI_SELL_THRESHOLD,
        "signal": signal,
        "signal_color": signal_color,
        "strategy": f"RSI({RSI_PERIOD}) EMA {RSI_BUY_THRESHOLD}/{RSI_SELL_THRESHOLD}",
        "backtest_return": f"{backtest_summary['classic_total']:.2f}%" if backtest_summary["classic_total"] is not None else "--",
        "backtest_annual": f"{backtest_summary['classic_annual']:.2f}%" if backtest_summary["classic_annual"] is not None else "--",
        "timestamp": beijing_time.strftime("%Y-%m-%d %H:%M:%S") + " (北京时间)"
    }
    
    with open(os.path.join(docs_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"静态数据已保存至 {docs_dir}/data.json")

    dynamic_data = {
        "etf_code": ETF_CODE,
        "etf_name": ETF_NAME,
        "market_date": latest_date,
        "price": round(price, 4) if price else None,
        "rsi": round(dynamic_rsi, 2) if dynamic_rsi is not None else None,
        "rsi_period": dynamic_params["rsi_period"],
        "rsi_buy_base": dynamic_params["rsi_buy_base"],
        "rsi_sell_base": dynamic_params["rsi_sell_base"],
        "vol_window": dynamic_params["vol_window"],
        "k_vol": dynamic_params["k_vol"],
        "vol_anchor": dynamic_params["vol_anchor"],
        "volatility": dynamic_signal["volatility"] if dynamic_signal else None,
        "buy_threshold": dynamic_signal["buy_threshold"] if dynamic_signal else None,
        "sell_threshold": dynamic_signal["sell_threshold"] if dynamic_signal else None,
        "signal": dynamic_signal["signal"] if dynamic_signal else "未知",
        "signal_color": dynamic_signal["signal_color"] if dynamic_signal else "#8a8070",
        "backtest_return": f"{backtest_summary['dynamic_total']:.2f}%" if backtest_summary["dynamic_total"] is not None else "--",
        "backtest_annual": f"{backtest_summary['dynamic_annual']:.2f}%" if backtest_summary["dynamic_annual"] is not None else "--",
        "timestamp": beijing_time.strftime("%Y-%m-%d %H:%M:%S") + " (北京时间)"
    }

    with open(os.path.join(docs_dir, "dynamic_data.json"), "w", encoding="utf-8") as f:
        json.dump(dynamic_data, f, ensure_ascii=False, indent=2)
    print(f"动态信号数据已保存至 {docs_dir}/dynamic_data.json")

    # ==========================================
    # 动态注入订阅服务地址 (从环境变量)
    # ==========================================
    subscribe_worker_url = os.environ.get("SUBSCRIBE_WORKER_URL")
    formspree_id = os.environ.get("FORMSPREE_ID")
    
    index_path = os.path.join(docs_dir, "index.html")
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            updated = False
            
            # 注入 Worker URL
            if subscribe_worker_url and "__SUBSCRIBE_WORKER_URL__" in content:
                content = content.replace("__SUBSCRIBE_WORKER_URL__", subscribe_worker_url)
                print(f"已注入 Worker URL: {subscribe_worker_url}")
                updated = True
            
            # 注入 Formspree ID (备用方案)
            if formspree_id and "__FORMSPREE_ID__" in content:
                content = content.replace("__FORMSPREE_ID__", formspree_id)
                print(f"已注入 Formspree ID: {formspree_id}")
                updated = True
            
            if updated:
                with open(index_path, "w", encoding="utf-8") as f:
                    f.write(content)
                print("index.html 更新完成")
            else:
                print("index.html 中未找到需要替换的占位符，跳过。")
        except Exception as e:
            print(f"更新 index.html 失败: {e}")

if __name__ == "__main__":
    main()
