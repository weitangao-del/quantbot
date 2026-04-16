import time             
import sqlite3  
import json
import os
from google import genai
from google.genai import types
import akshare as ak
import ccxt
import urllib.parse
import requests
from datetime import datetime

# ==========================================
# 1. 核心配置区域 (云端安全直连版)
# ==========================================

# 🚨 核心改造 1：彻底删除本地代理！GitHub 的美国服务器自带全球网络
# 🚨 核心改造 2：从 GitHub Secrets 中读取加密环境变量，绝证明文写在代码里！
TELEGRAM_TOKEN = os.getenv("MACRO_BOT_TOKEN")  
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- A. 场内 ETF / LOF ---
ETF_HOLDINGS = {
    "501225": {"name": "全球芯片LOF", "shares": 1100, "tag":"芯片LOf"},   
    "588060": {"name": "科创50", "shares": 1500, "tag":"A股"},
    "513330": {"name": "恒生科技", "shares": 7300, "tag":"港股"},
    "159632": {"name": "纳指100 ETF", "shares": 2441, "tag":"美股"},      
    "518880": {"name": "黄金 ETF", "shares": 330, "tag":"黄金"}
}

# --- B. 场外基金 ---
FUND_HOLDINGS = {
    "017436": {"name": "美股综合(支付宝)", "shares": 1309, "tag":"美股"}, 
    "018258": {"name": "中证300", "shares": 2799, "tag":"A股"},
    "012920": {"name": "易方达全球成长", "shares": 644, "tag":"全球成长"},
}

# --- C. 加密货币 ---
CRYPTO_HOLDINGS = {
    "BTC/USDT": {"name": "比特币现货", "amount": 0.00531309},    
    "ETH/USDT": {"name": "以太坊现货", "amount": 0.15354492},
}

# ==========================================
# 2. Telegram 推送模块
# ==========================================
def send_telegram_message(report_text):
    print("\n正在通过 Telegram 发送报告...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # 顺手把 AI 喜欢生成的 Markdown 星号去掉，保持排版干净
    clean_text = report_text.replace("**", "") 
    
    # 把文本打包成一个 JSON 包裹
    payload = {
        "chat_id": CHAT_ID,
        "text": clean_text,
        "parse_mode": "HTML"
    }
    
    try:
        # 💥 核心修改：改用 POST 方法发送包裹，支持无限字数！
        response = requests.post(url, json=payload, timeout=15)
        
        if response.status_code == 200:
            print("✅ Telegram 报告推送成功！手机应该响了。")
        else:
            print(f"❌ 推送失败，错误代码: {response.status_code}, {response.text}")
    except Exception as e:
         print(f"❌ 推送网络连接失败: {e}")
# ------------------------------------------
# 模块：海马体 (SQLite 数据库写入)
# ------------------------------------------
def save_daily_snapshot(total_value, daily_profit):
    # 💥 核心改造 4：移除 Mac 的本地绝对路径，改为当前目录的相对路径
    db_path = "portfolio.db" 
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            date TEXT PRIMARY KEY,
            total_value REAL,
            daily_profit REAL
        )
    ''')
    
    today = datetime.now().strftime('%Y-%m-%d')
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO history (date, total_value, daily_profit) 
            VALUES (?, ?, ?)
        ''', (today, total_value, daily_profit))
        conn.commit()
        print("✅ 今日资产快照已存入临时数据库。")
    except Exception as e:
        print(f"⚠️ 数据库写入失败: {e}")
    finally:
        conn.close()

# ------------------------------------------
# 模块：外脑 (Gemini AI 智能投顾)
# ------------------------------------------
def get_ai_summary(report_text):
    print("🧠 正在呼叫 AI 大脑 (云端极速直连模式)...")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{
            "parts": [{
                "text": f"你是一位顶级的华尔街对冲基金经理。请阅读以下我今天的跨市场资产监控报告，用专业、犀利且极其简练的语言（字数不限），总结今天的宏观资金动向，对我的持仓头寸表现给出针对性的点拨，并对我今天的实盘盈亏表现给出你的点评。不要说废话，直接给出结论。\n\n今日实盘报告数据如下：\n{report_text}"
            }]
        }],
        "generationConfig": {
            "maxOutputTokens": 1500
        }
    }
    
    try:
        # 💥 核心改造 5：移除 proxies 参数
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        
        result = response.json()
        ai_text = result['candidates'][0]['content']['parts'][0]['text']
        
        return f"\n🤖 <b>AI 投顾点评:</b>\n{ai_text.strip()}\n"
        
    except requests.exceptions.Timeout:
         print("❌ AI 链接超时 (超过15秒没反应，强制砍断)")
         return f"\n⚠️ AI 点评暂时不可用 (网络连接超时，已跳过)\n"
    except Exception as e:
        print(f"❌ AI 链接底层报错: {e}")
        return f"\n⚠️ AI 点评暂时不可用 (API 请求报错)\n"

# ==========================================
# 3. 数据抓取与计算引擎
# ==========================================
def get_portfolio_status():
    print(f"正在生成跨市场资产监控报告 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})...\n")
    
    UP_SYM = "🟩" 
    DOWN_SYM = "🟥"
    FLAT_SYM = "⬜️"
    
    macro_results = [] 
    results = []       
    
    total_market_value = 0
    total_daily_profit = 0
    category_stats = {}
    
    def add_to_category(cat_name, val, prof):
        if cat_name not in category_stats:
            category_stats[cat_name] = {"value": 0.0, "profit": 0.0}
        category_stats[cat_name]["value"] += val
        category_stats[cat_name]["profit"] += prof
        # A1: 抓取核心 Crypto (走 MEXC 接口)
    try:
        exchange = ccxt.mexc()
        # 💥 把找不到的 PAXG 从这里的列表里剔除，只留 BTC 和 ETH
        macro_assets = [("BTC/USDT", "比特币 (BTC)"), ("ETH/USDT", "以太坊 (ETH)")]
        for symbol, name in macro_assets:
            ticker = exchange.fetch_ticker(symbol)
            price = ticker['last']
            change_pct = float(ticker.get('percentage', 0))
            trend = UP_SYM if change_pct > 0 else (DOWN_SYM if change_pct < 0 else FLAT_SYM)
            macro_results.append(f"🌍 {name}: ${price:,.2f} {trend} {change_pct:+.2f}%")
    except Exception as e:
        macro_results.append(f"⚠️ 宏观(Crypto)获取失败: {e}")

    # A1.5: 抓取国际黄金 (走 CoinGecko 聚合平台免费接口)
    try:
        cg_url = "https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd&include_24hr_change=true"
        cg_resp = requests.get(cg_url, timeout=10).json()
        gold_price = cg_resp['pax-gold']['usd']
        gold_change = cg_resp['pax-gold']['usd_24h_change']
        trend = UP_SYM if gold_change > 0 else (DOWN_SYM if gold_change < 0 else FLAT_SYM)
        macro_results.append(f"🌍 国际黄金 (盎司): ${gold_price:,.2f} {trend} {gold_change:+.2f}%")
    except Exception as e:
        macro_results.append(f"⚠️ 黄金获取失败: {e}")


    # A2: 抓取传统三大指数
    try:
        session = requests.Session()
        session.trust_env = False 
        macro_indices = [("sh000001", "上证指数"), ("hkHSI", "恒生指数"), ("us.IXIC", "纳斯达克")]
        for code, name in macro_indices:
            resp = session.get(f"http://qt.gtimg.cn/q={code}", timeout=5)
            if resp.status_code == 200 and "v_" in resp.text:
                parts = resp.text.split('~')
                if len(parts) > 32:
                    price = float(parts[3])
                    change_pct = float(parts[32])
                    trend = UP_SYM if change_pct > 0 else (DOWN_SYM if change_pct < 0 else FLAT_SYM)
                    macro_results.append(f"🏛️ {name}: {price:,.2f} {trend} {change_pct:+.2f}%")
    except Exception as e:
        macro_results.append(f"⚠️ 宏观(传统指数)获取失败: {e}")

    # 获取实时汇率
    try:
        rate_resp = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5).json()
        usd_to_cny = float(rate_resp['rates']['CNY'])
    except:
        usd_to_cny = 7.23 

    # 1. 个人 Crypto 持仓
    try:
        for symbol, data in CRYPTO_HOLDINGS.items():
            if data['amount'] > 0:
                ticker = exchange.fetch_ticker(symbol)
                price = ticker['last']
                change_pct = float(ticker.get('percentage', 0))
                value_cny = price * data['amount'] * usd_to_cny 
                profit = value_cny - (value_cny / (1 + change_pct / 100)) if change_pct != 0 else 0
                
                total_market_value += value_cny
                total_daily_profit += profit
                add_to_category("加密货币", value_cny, profit)
                trend = UP_SYM if change_pct > 0 else (DOWN_SYM if change_pct < 0 else FLAT_SYM)
                results.append(f"[Crypto] {data['name']}: ¥{value_cny:,.2f} {trend} {change_pct:+.2f}%")
    except Exception as e:
        pass 

    # 2. 个人场内 ETF
    try:
        for code, data in ETF_HOLDINGS.items():
            if data['shares'] > 0:
                prefix = "sh" if code.startswith("5") else "sz"
                resp = session.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=5)
                if resp.status_code == 200 and "v_" in resp.text:
                    parts = resp.text.split('~')
                    if len(parts) > 32:
                        price = float(parts[3])
                        change_pct = float(parts[32]) 
                        value = price * data['shares']
                        profit = value - (value / (1 + change_pct / 100)) if change_pct != 0 else 0
                            
                        total_market_value += value
                        total_daily_profit += profit
                        cat = data.get("tag", "其他资产")
                        add_to_category(cat, value, profit)
                            
                        trend = UP_SYM if change_pct > 0 else (DOWN_SYM if change_pct < 0 else FLAT_SYM)
                        results.append(f"[{cat}] {data['name']}: ¥{value:,.2f} {trend} {change_pct:+.2f}%")
    except:
        pass

    # 3. 个人场外基金
    try:
        for code, data in FUND_HOLDINGS.items():
            if data['shares'] > 0:
                fund_data = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
                if not fund_data.empty:
                    latest_nav = fund_data['单位净值'].iloc[-1]
                    try:
                        change_pct = float(str(fund_data['日增长率'].iloc[-1]).replace('%', ''))
                    except:
                        change_pct = 0.0
                    
                    value = latest_nav * data['shares']
                    profit = value - (value / (1 + change_pct / 100)) if change_pct != 0 else 0
                        
                    total_market_value += value
                    total_daily_profit += profit
                    cat = data.get("tag", "其他资产")
                    add_to_category(cat, value, profit)
                        
                    trend = UP_SYM if change_pct > 0 else (DOWN_SYM if change_pct < 0 else FLAT_SYM)
                    results.append(f"[{cat}] {data['name']}: ¥{value:,.2f} {trend} {change_pct:+.2f}%")
    except:
         pass

    # 终极拼装
    total_change_pct = (total_daily_profit / (total_market_value - total_daily_profit)) * 100 if (total_market_value - total_daily_profit) > 0 else 0.0
    total_trend = UP_SYM if total_daily_profit > 0 else (DOWN_SYM if total_daily_profit < 0 else FLAT_SYM)

    allocation_lines = ["\n📊 <b>我的底层资产配置与版块盈亏:</b>"]
    if total_market_value > 0:
        sorted_cats = sorted(category_stats.items(), key=lambda x: x[1]["value"], reverse=True)
        for cat, stats in sorted_cats:
            if stats["value"] > 0:
                pct = (stats["value"] / total_market_value) * 100
                blocks = int(round(pct / 10))
                bar = "■" * blocks + "□" * (10 - blocks)
                cat_prof = stats["profit"]
                prof_trend = UP_SYM if cat_prof > 0 else (DOWN_SYM if cat_prof < 0 else FLAT_SYM)
                allocation_lines.append(f"▫️ {cat}: {pct:>4.1f}% {bar} | {prof_trend} ¥{abs(cat_prof):.0f}")

    report_lines = [
        f"🏆 <b>私人资管雷达 (GitHub 云端架构版)</b>",
        f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')} | 💱 汇率: {usd_to_cny:.4f}",
        "========================================"
    ]
    
    report_lines.append("🌐 <b>全球宏观风向标</b>")
    report_lines.extend(macro_results)
    report_lines.append("----------------------------------------")
    
    report_lines.append("💼 <b>个人核心持仓明细</b>")
    report_lines.extend(results)
    
    report_lines.extend(allocation_lines) 
    report_lines.append("========================================")
    report_lines.append(f"💰 <b>全天候总市值: ¥ {total_market_value:,.2f}</b>")
    report_lines.append(f"🔥 <b>全盘总盈亏: {total_trend} ¥ {abs(total_daily_profit):,.2f} ({total_change_pct:+.2f}%)</b>")

    final_report = "\n".join(report_lines)
    
    save_daily_snapshot(total_market_value, total_daily_profit)
    
    ai_comment = get_ai_summary(final_report)
    final_report += ai_comment
    
    print(final_report)
    send_telegram_message(final_report)

if __name__ == "__main__":
    get_portfolio_status()
