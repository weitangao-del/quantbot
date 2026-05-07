import time             
import sqlite3  
import json
import os
import csv
from io import StringIO
from datetime import datetime, timedelta
import requests
import ccxt
import akshare as ak
import yfinance as yf

# ==========================================
# 1. 核心配置区域 (云原生安全解耦版)
# ==========================================
TELEGRAM_TOKEN = os.getenv("MACRO_BOT_TOKEN")  
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CSV_URL = os.getenv("PORTFOLIO_CSV_URL") 

# 🎯 价值投资与永久组合的"锚点"
TARGET_WEIGHTS = {
    "US_TECH": 0.50,   # 美股/芯片/全球成长 (调高以适应 8-2 舰队)
    "CN_HK": 0.05,     # A股/港股宽基
    "CRYPTO": 0.10,    # 加密货币高波资产
    "GOLD": 0.15,      # 黄金底仓
    "CASH": 0.20       # 战略现金池
}

# 🎯 阶梯击球区与火力分配矩阵：[(回撤%, 动用现金池比例%)]
STRIKING_ZONES = {
    "US_TECH": [(35, 0.50), (25, 0.30), (15, 0.15)], 
    "CN_HK": [(30, 0.20), (20, 0.10)],
    "CRYPTO": [(70, 0.30), (50, 0.20), (30, 0.10)]
}

UP_SYM = "🟩" 
DOWN_SYM = "🟥"
FLAT_SYM = "⬜️"

# ==========================================
# 2. 核心工具与通信模块
# ==========================================
def send_telegram_message(report_text):
    print("\n正在通过 Telegram 发送报告...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    clean_text = report_text.replace("**", "") 
    payload = {
        "chat_id": CHAT_ID,
        "text": clean_text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            print("✅ Telegram 推送成功！")
        else:
            print(f"❌ 推送失败: {response.status_code}, {response.text}")
    except Exception as e:
         print(f"❌ 推送网络错误: {e}")

def save_daily_snapshot(total_value, daily_profit):
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
    except Exception as e:
        print(f"⚠️ 数据库写入失败: {e}")
    finally:
        conn.close()

def sync_to_cloud_history(total_value, daily_profit):
    webhook_url = os.getenv("HISTORY_WEBAPP_URL")
    if not webhook_url:
        print("⚠️ 未配置 HISTORY_WEBAPP_URL，跳过云端同步。")
        return

    payload = {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "total_value": round(total_value, 2),
        "daily_profit": round(daily_profit, 2)
    }
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=15)
        if "Success" in response.text:
            print("📈 历史数据已成功同步至 Google Sheets History 表。")
    except Exception as e:
        print(f"❌ 云端历史同步失败: {e}")

# ==========================================
# 3. 击球区追踪引擎 (Max Drawdown Radar)
# ==========================================
def check_macro_drawdown(current_cash_value):
    print("📡 正在扫描宏观击球区与测算火力分配...")
    alerts = []
    try:
        qqq = yf.download("QQQ", period="1y", progress=False)
        if not qqq.empty:
            high_1y = float(qqq['High'].max())
            current = float(qqq['Close'].iloc[-1])
            dd_pct = abs((current - high_1y) / high_1y * 100)
            
            for zone_pct, cash_ratio in STRIKING_ZONES["US_TECH"]:
                if dd_pct >= zone_pct:
                    deploy_amount = current_cash_value * cash_ratio
                    alerts.append(f"🎯 <b>美股击球区</b>: 纳指回撤 {dd_pct:.1f}% (触及 {zone_pct}% 防线)。\n"
                                  f"   👉 战术指令: 动用现金池 {cash_ratio*100:.0f}% (约 ¥{deploy_amount:,.0f}) 加仓！")
                    break 

        btc = yf.download("BTC-USD", period="1y", progress=False)
        if not btc.empty:
            high_1y = float(btc['High'].max())
            current = float(btc['Close'].iloc[-1])
            dd_pct = abs((current - high_1y) / high_1y * 100)
            
            for zone_pct, cash_ratio in STRIKING_ZONES["CRYPTO"]:
                if dd_pct >= zone_pct:
                    deploy_amount = current_cash_value * cash_ratio
                    alerts.append(f"🌋 <b>Crypto击球区</b>: BTC回撤 {dd_pct:.1f}% (触及 {zone_pct}% 防线)。\n"
                                  f"   👉 战术指令: 动用现金池 {cash_ratio*100:.0f}% (约 ¥{deploy_amount:,.0f}) 抄底！")
                    break
    except Exception as e:
        print(f"⚠️ 击球区雷达报错跳过: {e}")
        
    return alerts

# ==========================================
# 4. 外脑: 芒格视角的 Gemini 架构
# ==========================================
def get_ai_summary(report_text, dev_text, alerts_text):
    print("🧠 正在呼叫云端 AI 智囊...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    sys_prompt = (
        "你现在是我私人的『芒格派首席风控官』。你的核心哲学是：忽略短期宏观噪音，关注资产护城河，严格执行资产配置再平衡策略。\n"
        "请阅读以下我的今日盘面数据、目标仓位偏离度以及击球区警报。给出极其犀利、冷酷的建议。\n"
        "1. 如果某类资产严重偏离目标比重，强制要求我执行高抛低吸。\n"
        "2. 🚨 如果击球区警报响起，严格按照系统计算的『金额』敦促我执行，不准自己瞎编。\n"
        "3. 对今日盈亏一句话冷血点评（盈亏同源，无需安慰）。\n"
    )
    
    full_context = f"【今日盘面】\n{report_text}\n\n【再平衡诊断】\n{dev_text}\n\n【警报】\n{alerts_text}"
    payload = {
        "contents": [{"parts": [{"text": sys_prompt + "\n\n" + full_context}]}],
        "generationConfig": {"maxOutputTokens": 2048}
    }
    
    try:
        response = requests.post(url, json=payload, timeout=45)
        response.raise_for_status()
        ai_text = response.json()['candidates'][0]['content']['parts'][0]['text']
        return f"\n🤖 <b>芒格智囊点评:</b>\n{ai_text.strip()}\n"
    except Exception as e:
        return f"\n⚠️ AI 智囊暂时离线 ({e})\n"

# ==========================================
# 5. 主循环: 动态路由与抓取引擎
# ==========================================
def get_portfolio_status():
    print(f"🚀 启动跨市场全天候监控引擎 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})...\n")
    
    if not CSV_URL:
        print("❌ 致命错误: 未配置 PORTFOLIO_CSV_URL。程序终止。")
        return

    # --- 1. 获取多币种汇率与宏观数据 ---
    macro_results = []
    rates = {"CNY": 1.0, "USD": 7.25, "HKD": 0.93} # 兜底汇率
    rate_changes = {"USD": 0.0, "HKD": 0.0}

    try:
        for pair, key in [("USDCNY=X", "USD"), ("HKDCNY=X", "HKD")]:
            fx_data = yf.download(pair, period="5d", progress=False)
            if len(fx_data) >= 2:
                current_rate = float(fx_data['Close'].iloc[-1])
                prev_rate = float(fx_data['Close'].iloc[-2])
                rates[key] = current_rate
                rate_changes[key] = (current_rate - prev_rate) / prev_rate * 100
    except Exception as e:
        print(f"⚠️ 实时汇率通道受阻，启用系统兜底汇率 ({e})")

    usd_trend = UP_SYM if rate_changes["USD"] > 0 else (DOWN_SYM if rate_changes["USD"] < 0 else FLAT_SYM)
    hkd_trend = UP_SYM if rate_changes["HKD"] > 0 else (DOWN_SYM if rate_changes["HKD"] < 0 else FLAT_SYM)
    macro_results.append(f"💱 汇率中枢 | USD: {rates['USD']:.4f} {usd_trend} {rate_changes['USD']:+.2f}% | HKD: {rates['HKD']:.4f} {hkd_trend} {rate_changes['HKD']:+.2f}%")
    
    # 获取其他宏观资产
    try:
        cg_resp = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd&include_24hr_change=true", timeout=10).json()
        gold_change = cg_resp['pax-gold']['usd_24h_change']
        macro_results.append(f"🌍 国际黄金: ${cg_resp['pax-gold']['usd']:,.2f} {UP_SYM if gold_change>0 else DOWN_SYM} {gold_change:+.2f}%")
        
        session = requests.Session()
        session.trust_env = False 
        for code, name in [("us.IXIC", "纳斯达克"), ("hkHSI", "恒生指数")]: # 更新宏观看板
            resp = session.get(f"http://qt.gtimg.cn/q={code}", timeout=5)
            if "v_" in resp.text:
                parts = resp.text.split('~')
                macro_results.append(f"🏛️ {name}: {float(parts[3]):,.2f} {UP_SYM if float(parts[32])>0 else DOWN_SYM} {float(parts[32]):+.2f}%")
    except Exception as e:
        macro_results.append(f"⚠️ 宏观获取失败: {e}")

    # --- 2. 拉取云端表格并路由计算 ---
    total_market_value = 0.0
    total_daily_profit = 0.0
    category_stats = {k: {"value": 0.0, "profit": 0.0} for k in TARGET_WEIGHTS.keys()}
    results = []

    try:
        csv_resp = requests.get(CSV_URL, timeout=15)
        csv_resp.encoding = 'utf-8'
        reader = csv.DictReader(StringIO(csv_resp.text))
        exchange = ccxt.mexc()
        
        for row in reader:
            asset_id = row['Asset_ID'].strip()
            asset_name = row.get('Asset_Name', asset_id).strip() 
            qty = float(row['Quantity'].strip())
            cat = row['Category'].strip()
            source = row['Data_Source'].strip()
            currency = row.get('Currency', 'CNY').strip().upper() # 提取表格币种
            
            val_local = 0.0
            profit_local = 0.0
            change_pct = 0.0

            try:
                if source == 'FIXED': # 现金池 (支持外币)
                    val_local = qty
                    profit_local = 0.0
                    change_pct = 0.0
                
                elif asset_id.startswith('f') or source == 'AKSHARE_FUND': 
                    clean_code = asset_id.replace('f', '')
                    fund_data = ak.fund_open_fund_info_em(symbol=clean_code, indicator="单位净值走势")
                    if not fund_data.empty:
                        price = fund_data['单位净值'].iloc[-1]
                        val_local = price * qty
                        try:
                            change_pct = float(str(fund_data['日增长率'].iloc[-1]).replace('%', ''))
                            profit_local = val_local - (val_local / (1 + change_pct / 100))
                        except:
                            pass
                    else:
                        raise Exception("Akshare 未返回数据")

                elif source == 'TENCENT': # 场内ETF/A股/港股/美股
                    resp = session.get(f"http://qt.gtimg.cn/q={asset_id}", timeout=5)
                    resp.encoding = 'gbk' 
                    if "v_" in resp.text:
                        parts = resp.text.split('~')
                        price = float(parts[3])
                        change_pct = float(parts[32])
                        val_local = price * qty
                        profit_local = val_local - (val_local / (1 + change_pct / 100)) if change_pct != 0 else 0

                elif source == 'CCXT_MEXC': # 加密货币
                    ticker = exchange.fetch_ticker(asset_id)
                    price = ticker['last']
                    change_pct = float(ticker.get('percentage', 0))
                    val_local = price * qty 
                    profit_local = val_local - (val_local / (1 + change_pct / 100)) if change_pct != 0 else 0
                    currency = 'USD' # 强制覆写为美元结算

                # --- 核心折算引擎 (多币种统一归拢人民币) ---
                conv_rate = rates.get(currency, 1.0)
                val_cny = val_local * conv_rate
                profit_cny = profit_local * conv_rate

                if cat in category_stats:
                    category_stats[cat]["value"] += val_cny
                    category_stats[cat]["profit"] += profit_cny
                total_market_value += val_cny
                total_daily_profit += total_daily_profit
                
                trend = UP_SYM if change_pct > 0 else (DOWN_SYM if change_pct < 0 else FLAT_SYM)
                # 播报格式: 显示本币面额 + 折合人民币面额
                if currency != 'CNY':
                    results.append(f"[{cat}] {asset_name}: {currency} {val_local:,.2f} (折¥{val_cny:,.2f}) {trend} {change_pct:+.2f}%")
                else:
                    results.append(f"[{cat}] {asset_name}: ¥{val_cny:,.2f} {trend} {change_pct:+.2f}%")

            except Exception as e:
                print(f"⚠️ {asset_name} 抓取异常: {e}")
                results.append(f"❌ [{cat}] {asset_name}: 抓取失败，已跳过 ({source})")
            
    except Exception as e:
        print(f"❌ 云端表格读取失败: {e}")
        return

    # --- 3. 核心再平衡逻辑测算 (Rebalance Engine) ---
    dev_lines = ["\n⚖️ <b>资产配置偏离度诊断:</b>"]
    for cat, target in TARGET_WEIGHTS.items():
        actual_val = category_stats[cat]["value"]
        actual_ratio = actual_val / total_market_value if total_market_value > 0 else 0
        diff = actual_ratio - target
        
        status_icon = "✅" if abs(diff) < 0.05 else ("🔴 超标" if diff > 0 else "🟢 低配")
        dev_lines.append(f"▫️ {cat}: 实际 {actual_ratio*100:>4.1f}% | 目标 {target*100:>4.1f}% | 偏离 {diff*100:>+5.1f}% {status_icon}")
    dev_text = "\n".join(dev_lines)

    # --- 4. 击球区狙击预警 ---
    current_cash_value = category_stats.get("CASH", {}).get("value", 0.0) # 这里的现金已经是折算后的 CNY 总量
    striking_alerts = check_macro_drawdown(current_cash_value)
    alerts_text = "\n".join(striking_alerts) if striking_alerts else "当前未触发击球区，保持现金底仓耐心等待。"

    # --- 5. 终极拼装与发送 ---
    total_change_pct = (total_daily_profit / (total_market_value - total_daily_profit)) * 100 if (total_market_value - total_daily_profit) > 0 else 0.0
    total_trend = UP_SYM if total_daily_profit > 0 else (DOWN_SYM if total_daily_profit < 0 else FLAT_SYM)

    report_lines = [
        f"🏆 <b>私人资管引擎 (多币种跨市场版)</b>",
        f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')} | 运行于 GitHub Actions",
        "========================================"
    ]
    report_lines.append("🌐 <b>全球宏观风向标</b>")
    report_lines.extend(macro_results)
    report_lines.append("----------------------------------------")
    report_lines.append("💼 <b>底层资产明细 (本币 & 折合人民币)</b>")
    report_lines.extend(results)
    report_lines.append("----------------------------------------")
    report_lines.append(dev_text)
    report_lines.append("----------------------------------------")
    report_lines.append("🚨 <b>系统行动指令</b>")
    report_lines.append(alerts_text)
    report_lines.append("========================================")
    report_lines.append(f"💰 <b>包含外币现金总AUM: ¥ {total_market_value:,.2f}</b>")
    report_lines.append(f"🔥 <b>实盘波动浮亏: {total_trend} ¥ {abs(total_daily_profit):,.2f} ({total_change_pct:+.2f}%)</b>")

    final_report = "\n".join(report_lines)
    save_daily_snapshot(total_market_value, total_daily_profit)
    
    ai_comment = get_ai_summary(final_report, dev_text, alerts_text)
    final_report += ai_comment
    
    print(final_report)
    send_telegram_message(final_report)
    sync_to_cloud_history(total_market_value, total_daily_profit)

if __name__ == "__main__":
    get_portfolio_status()
