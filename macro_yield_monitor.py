import os
import requests
import time

# --- 核心环境变量 ---
FRED_API_KEY = os.getenv('FRED_API_KEY')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MACRO_BOT_TOKEN = os.getenv('MACRO_BOT_TOKEN')

def get_fred_latest_value(series_id, log_name):
    """
    通用 FRED 数据抓取引擎 (带3次重试与缺省值容错)
    系列代码映射:
    DGS10: 10年期美债收益率
    DGS2:  2年期美债收益率
    BAMLH0A0HYM2: 高收益债 OAS 利差
    """
    if not FRED_API_KEY:
        print(f"⚠️ 缺少 FRED_API_KEY，跳过 {log_name}")
        return None, None

    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1
    }

    for attempt in range(3):
        try:
            # 严格超时，无代理直连
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                obs = resp.json().get('observations', [])
                if not obs:
                    continue
                
                # 获取最新数据，处理 FRED 节假日无数据的 "." 标记
                val_str = obs[0].get('value', '.')
                date_str = obs[0].get('date', 'Unknown')
                
                if val_str != ".":
                    return float(val_str), date_str
            else:
                print(f"⚠️ FRED API 状态码异常: {resp.status_code}")
                
        except Exception as e:
            print(f"⚠️ {log_name} 抓取重试 ({attempt+1}/3): {e}")
            time.sleep(3)
            
    return None, None

def send_telegram_alert(text):
    """TG 机器人推送 (JSON Payload 突破长度限制)"""
    if not MACRO_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TG 配置缺失，无法推送")
        return
        
    url = f"https://api.telegram.org/bot{MACRO_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ TG 发送彻底失败: {e}")

def main():
    print("🚀 启动 7x24 纯血宏观监控引擎 (FRED Native)...")
    
    # 1. 并发请求 FRED 核心宏观指标
    y10_val, y10_date = get_fred_latest_value("DGS10", "10Y收益率")
    y2_val, _ = get_fred_latest_value("DGS2", "2Y收益率")
    oas_val, oas_date = get_fred_latest_value("BAMLH0A0HYM2", "OAS利差")

    # 2. 数据处理与倒挂计算
    report_lines = [
        "🏛 **美债宏观投研监控**",
        "—" * 15
    ]

    # --- 收益率板块 ---
    if y10_val is not None and y2_val is not None:
        inv_val = round(y10_val - y2_val, 4)
        report_lines.extend([
            "📈 **国债基准利率:**",
            f"- 10Y Yield: `{y10_val}%`",
            f"- 2Y Yield: `{y2_val}%`",
            f"- 倒挂利差: `{inv_val}%`",
            f"_(数据更新: {y10_date})_\n"
        ])
    else:
        report_lines.append("⚠️ **国债基准利率:** 数据获取失败 (请检查 FRED Key)\n")

    # --- 信用利差 (OAS) 板块 ---
    if oas_val is not None:
        status = "🔴 恐慌" if oas_val >= 6.0 else ("🟡 预警" if oas_val >= 4.5 else "🟢 平稳")
        report_lines.extend([
            "🚨 **信用风险 (OAS 溢价):**",
            f"- 当前数值: `{oas_val}%`",
            f"- 市场状态: {status}",
            f"_(数据更新: {oas_date})_"
        ])
    else:
        report_lines.append("⚠️ **信用风险 (OAS):** 数据获取失败\n")

    # 3. 组装并发送
    final_report = "\n".join(report_lines)
    send_telegram_alert(final_report)
    print("✅ 执行完毕，报表已下发。")

if __name__ == "__main__":
    main()
