import os
import requests
import yfinance as yf
from datetime import datetime, timedelta

# --- 配置区：你的真实持仓映射 ---
PORTFOLIO = {
    "BTC-USD": 0.10,     # 加密货币部分
    "ETH-USD": 0.096,    
    "QQQ": 0.307,        # 纳指 100 ETF
    "GLD": 0.126,        # 黄金 ETF
    "KWEB": 0.123,       # 恒生科技 (海外上市近似)
    "SOXX": 0.117,       # 芯片半导体
    "MCHI": 0.079,       # 全球成长/中国大盘
    "ASHR": 0.051        # A股科创/沪深300近似
}

def send_telegram_msg(text):
    """
    通过 GitHub Secrets 获取密钥，直连推送
    """
    token = os.getenv('MACRO_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print("❌ 错误：未找到 Telegram 密钥配置")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=30)
        print(f"📡 TG 推送状态: {resp.status_code}")
    except Exception as e:
        print(f"❌ TG 发送失败: {e}")

def run_backtest():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    total_return = 0.0
    
    msg_lines = ["🚀 **1年期资产收益回测报告**", f"📅 时间范围: {start_date.strftime('%Y-%m-%d')} -> 至今", ""]
    
    for ticker, weight in PORTFOLIO.items():
        try:
            # GitHub 环境直连 Yahoo Finance
            df = yf.download(ticker, start=start_date.strftime('%Y-%m-%d'), progress=False, timeout=30)
            if not df.empty:
                p_start = float(df['Close'].iloc[0])
                p_end = float(df['Close'].iloc[-1])
                asset_ret = (p_end - p_start) / p_start
                weighted_ret = asset_ret * weight
                total_return += weighted_ret
                
                icon = "🟩" if asset_ret > 0 else "🟥"
                msg_lines.append(f"{icon} `{ticker:<8}`: {asset_ret:>+7.2%}")
        except Exception as e:
            msg_lines.append(f"⚠️ `{ticker}` 抓取失败: {e}")

    msg_lines.append("")
    msg_lines.append(f"💰 **全盘理论总收益: {total_return:+.2%}**")
    msg_lines.append(f"💡 *注：基于截图权重的静态持有假设*")
    
    full_msg = "\n".join(msg_lines)
    print(full_msg) # 在 Actions 日志中可见
    send_telegram_msg(full_msg)

if __name__ == "__main__":
    run_backtest()
