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
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            current_yield = data['chart']['result'][0]['meta']['regularMarketPrice']
            return current_yield
            
        except Exception as e:
            print(f"⚠️ [{name}] 第 {attempt} 次抓取失败: {e}")
            if attempt < 3:
                time.sleep(5)
            else:
                return None

# ================= 新增：美联储降息预期模块 =================
def get_fed_funds_futures():
    """
    通过 30天联邦基金利率期货 (ZQ=F) 逆推市场降息预期
    """
    # 抓取当前月合约
    price = fetch_yahoo_yield("ZQ=F", "联邦基金利率期货(ZQ=F)")
    if price:
        # 隐含利率 = 100 - 期货价格
        implied_rate = 100 - price
        return implied_rate
    return None

def analyze_fed_sentiment(implied_rate):
    """
    基于隐含利率对比当前基准利率，输出市场下注倾向
    (注：当前 2026 年设定基准利率参考上限为 5.50%，可依实际宏观情况调整)
    """
    CURRENT_UPPER_BOUND = 5.50  
    spread = CURRENT_UPPER_BOUND - implied_rate
    
    if spread > 0.40:
        return f"🔴 强烈降息预期 (定价约 50bps 降幅) | 隐含利率: {implied_rate:.2f}%"
    elif spread > 0.15:
        return f"🟡 稳健降息预期 (定价约 25bps 降幅) | 隐含利率: {implied_rate:.2f}%"
    elif abs(spread) <= 0.15:
        return f"⚪ 维持现状 (按兵不动) | 隐含利率: {implied_rate:.2f}%"
    else:
        return f"⚠️ 加息预警 (市场定价紧缩) | 隐含利率: {implied_rate:.2f}%"
# =========================================================

def send_telegram_alert(message):
    """
    发送 Telegram 消息
    """
    bot_token = os.getenv("MACRO_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("❌ 环境变量缺失，取消 Telegram 发送。")
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
    print("🚀 开始执行宏观无风险利率及美联储预期监控...")
    
    # 1. 抓取美债数据
    yield_10y = fetch_yahoo_yield("^TNX", "10年期美债")
    yield_3m = fetch_yahoo_yield("^IRX", "3个月期美债(T-Bill)")
    
    # 2. 抓取美联储期货数据 (新增)
    fed_implied_rate = get_fed_funds_futures()
    
    if yield_10y is None or yield_3m is None:
        print("❌ 核心数据抓取失败，终止本次宏观评估。")
        return

    # 构建衰退预警逻辑
    inversion_alert = ""
    if yield_3m > yield_10y:
        inversion_alert = f"🚨 深度倒挂 (3M: {yield_3m:.2f}% > 10Y: {yield_10y:.2f}%) - 衰退定价中"
    else:
        inversion_alert = "✅ 正常 (未倒挂)"

    # 构建降息预期文本 (新增)
    fed_sentiment = analyze_fed_sentiment(fed_implied_rate) if fed_implied_rate else "⚠️ 数据获取失败"

    # 生成最终汇报文本 (整合新增数据)
    report = (
        "🏦 **【全球宏观资产雷达 & 美联储观察】**\n"
        "------------------------\n"
        f"🇺🇸 10年期美债收益率: **{yield_10y:.2f}%** (全球定价锚)\n"
        f"🛡️ 3个月期美债收益率: **{yield_3m:.2f}%** (无风险避风港)\n"
        f"🦅 **美联储近期预期**: {fed_sentiment}\n\n"
        f"📊 **收益率曲线状态**: {inversion_alert}\n\n"
        "💡 **架构师策略提示**:\n"
    )
    
    # 动态策略点评
    if yield_3m > 5.0 and fed_implied_rate and fed_implied_rate < 5.0:
        report += "前端无风险收益极高，但期货市场正在抢跑降息。当前是锁定长期美债收益率的最后窗口，加密货币等风险资产将迎来流动性利好。"
    elif yield_10y < 3.5:
        report += "长端资金成本极低，流动性极其充裕。风险资产（BTC、纳斯达克）处于黄金做多窗口期。"
    else:
        report += "宏观利率处于中性震荡区，请结合 USD/CNY 汇率表现决定是否进行资产置换。"

    print("--- 报表生成完毕 ---")
    print(report)
    send_telegram_alert(report)

if __name__ == "__main__":
    main()
