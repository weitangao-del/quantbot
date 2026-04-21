import os
import time
import requests

# Yahoo Finance 接口地址
YAHOO_API_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

# 伪装头，防止 Yahoo 拦截 GitHub Actions 的默认 Python-urllib 标头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

def fetch_yahoo_yield(ticker, name):
    """
    抓取 Yahoo Finance 的收益率数据，带 3 次重试与 30 秒超时
    """
    url = YAHOO_API_URL.format(ticker=ticker)
    
    for attempt in range(1, 4):
        try:
            # 严格规范：timeout=30，全网直连（无 proxy）
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            # 解析 Yahoo 底层 JSON 拿到最新现价
            current_yield = data['chart']['result'][0]['meta']['regularMarketPrice']
            return current_yield
            
        except Exception as e:
            print(f"⚠️ [{name}] 第 {attempt} 次抓取失败: {e}")
            if attempt < 3:
                time.sleep(5)  # 退避重试
            else:
                return None

def send_telegram_alert(message):
    """
    必须使用 POST JSON payload 发送 Telegram 消息，防止长文本截断
    """
    bot_token = os.getenv("MACRO_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("❌ 环境变量 MACRO_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未设置，取消发送。")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        print("✅ Telegram 宏观简报发送成功")
    except Exception as e:
        print(f"❌ Telegram 发送失败: {e}")

def main():
    print("🚀 开始执行宏观无风险利率监控...")
    
    # ^TNX = 10年期美债, ^IRX = 13周(3个月)短期美债(无风险利率完美代理)
    yield_10y = fetch_yahoo_yield("^TNX", "10年期美债")
    yield_3m = fetch_yahoo_yield("^IRX", "3个月期美债(T-Bill)")
    
    if yield_10y is None or yield_3m is None:
        print("❌ 核心数据抓取失败，终止本次宏观评估。")
        return

    # 构建评估逻辑
    inversion_alert = ""
    if yield_3m > yield_10y:
        inversion_alert = f"🚨 **警报**：收益率曲线深度倒挂 (3M: {yield_3m:.2f}% > 10Y: {yield_10y:.2f}%)，衰退定价中！"
    else:
        inversion_alert = "✅ 收益率曲线正常"

    # 生成汇报文本
    report = (
        "🏦 **【全球宏观资产雷达】**\n"
        "------------------------\n"
        f"🇺🇸 10年期美债收益率: **{yield_10y:.2f}%** (全球定价锚)\n"
        f"🛡️ 3个月期美债收益率: **{yield_3m:.2f}%** (无风险避风港)\n\n"
        f"📊 **曲线状态**: {inversion_alert}\n\n"
        "💡 **架构师策略提示**:\n"
    )
    
    # 极简的“无风险 vs 风险”评估逻辑
    if yield_3m > 5.0:
        report += "当前无风险收益率极高。若汇率合适，持有美债/美元现金是极佳的防御策略，建议压低加密货币与长久期科技股仓位。"
    elif yield_10y < 3.5:
        report += "流动性极其充裕，长端资金成本极低。是风险资产（BTC、纳斯达克）做多的黄金窗口。"
    else:
        report += "利率处于中性震荡区，建议保持底层监控，等待汇率或美元指数的明确信号。"

    print("--- 报表生成完毕 ---")
    print(report)
    send_telegram_alert(report)

if __name__ == "__main__":
    main()
