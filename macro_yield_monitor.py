import os
import requests
import time

# --- 1. 环境变量安全读取 ---
FRED_API_KEY = os.getenv('FRED_API_KEY')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MACRO_BOT_TOKEN = os.getenv('MACRO_BOT_TOKEN')

def get_us_yields():
    """获取美债收益率 - 腾讯财经源 (直连稳健)"""
    yields = {}
    symbols = {'10Y': 'us10Y', '2Y': 'us2Y'}
    try:
        for label, sym in symbols.items():
            url = f"https://qt.gtimg.cn/q={sym}"
            for _ in range(3):
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    parts = resp.text.split('~')
                    if len(parts) > 3:
                        yields[label] = float(parts[3])
                        break
            time.sleep(1)
    except Exception as e:
        print(f"⚠️ 收益率抓取异常: {e}")
    return yields

def get_us_bond_oas():
    """获取美债 OAS 利差 - FRED 源 (增加严格类型检查)"""
    if not FRED_API_KEY:
        return None
        
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": "BAMLH0A0HYM2",
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1
    }
    
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                obs = data.get('observations', [])[0]
                val_str = obs.get('value', '.')
                if val_str == ".": continue 
                
                val = float(val_str)
                status = "🔴 恐慌" if val > 6.0 else ("🟡 预警" if val > 4.5 else "🟢 平稳")
                return {"val": val, "date": obs.get('date', 'Unknown'), "status": status}
        except Exception as e:
            print(f"OAS 重试 ({attempt+1}/3): {e}")
            time.sleep(5)
    return None

def send_telegram_report(content):
    """JSON Payload 发送，突破长度限制"""
    if not MACRO_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TG 配置缺失")
        return
    
    url = f"https://api.telegram.org/bot{MACRO_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": content, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=30)
    except Exception as e:
        print(f"❌ TG 发送失败: {e}")

def main():
    print("🚀 启动 7x24 宏观监控系统...")
    
    # 1. 抓取国债数据
    yield_data = get_us_yields()
    y10 = yield_data.get('10Y', 0.0)
    y2 = yield_data.get('2Y', 0.0)
    inv_val = round(y10 - y2, 4) if y10 and y2 else "N/A"

    # 2. 抓取 OAS 数据 (核心修复：严格判断字典类型)
    oas_data = get_us_bond_oas()
    
    # 3. 组装报告内容
    report_header = "🏛 **美债宏观投研监控**\n" + "—" * 15 + "\n"
    yield_section = (f"📈 **国债收益率:**\n"
                     f"- 10Y Yield: `{y10}%` \n"
                     f"- 2Y Yield: `{y2}%` \n"
                     f"- 倒挂利差: `{inv_val}%` \n\n")
    
    if isinstance(oas_data, dict):
        oas_section = (f"🚨 **危机监控 (OAS 利差):**\n"
                       f"- 当前值: `{oas_data['val']}%` \n"
                       f"- 状态: {oas_data['status']} \n"
                       f"- 更新日期: {oas_data['date']}\n")
    else:
        oas_section = "⚠️ OAS 数据暂时无法获取 (FRED API 延迟)\n"

    # 4. 执行发送
    send_telegram_report(report_header + yield_section + oas_section)
    print("✅ 任务完成，报告已送达。")

if __name__ == "__main__":
    main()
