import os
import requests
import time

# --- 环境变量 ---
FRED_API_KEY = os.getenv('FRED_API_KEY')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MACRO_BOT_TOKEN = os.getenv('MACRO_BOT_TOKEN')

def get_us_yields():
    """纯原生实现，不依赖 pandas"""
    yields = {}
    symbols = {'10Y': 'us10Y', '2Y': 'us2Y'}
    try:
        for label, sym in symbols.items():
            url = f"https://qt.gtimg.cn/q={sym}"
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                parts = resp.text.split('~')
                if len(parts) > 3:
                    yields[label] = float(parts[3])
    except Exception as e:
        print(f"收益率获取失败: {e}")
    return yields

def get_us_bond_oas():
    """
    模块2：获取美债信用风险溢价 (新增 OAS 功能)
    """
    if not FRED_API_KEY:
        return "⚠️ FRED_API_KEY 未配置"
        
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
                obs = data['observations'][0]
                val_str = obs['value']
                if val_str == ".": continue # 处理 FRED 缺失值
                
                val = float(val_str)
                status = "🔴 恐慌" if val > 6.0 else ("🟡 预警" if val > 4.5 else "🟢 平稳")
                return {"val": val, "date": obs['date'], "status": status}
        # --- 找到函数最后两行，按此修改 ---
    except Exception as e:
        print(f"代码逻辑异常: {e}")
        # 删掉 break
            
    return None  # 抓取失败统一返回 None，不要返回报错字符串

def send_telegram_report(content):
    """
    模块3：通过 JSON Payload 发送长文本通知
    """
    url = f"https://api.telegram.org/bot{MACRO_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": content,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        return r.json()
    except Exception as e:
        print(f"❌ TG 发送失败: {e}")

def main():
    print("🚀 启动 7x24 全自动化宏观监控...")
    
    # 1. 抓取收益率
    yield_data = get_us_yields()
    y10 = yield_data.get('10Y', 'N/A')
    y2 = yield_data.get('2Y', 'N/A')
    inv_val = round(y10 - y2, 4) if isinstance(y10, float) and isinstance(y2, float) else "N/A"

    # 2. 抓取 OAS
# --- 找到 main 里的 oas_section 组装部分 ---
    oas_data = get_us_bond_oas()
    
    if isinstance(oas_data, dict): # 严格检查是否为字典
        oas_section = (f"危机监控 (OAS 利差):\n"
                       f"- 当前值: `{oas_data['val']}%` \n"
                       f"- 状态: {oas_data['status']} \n"
                       f"- 更新日期: {oas_data['date']}\n")
    else:
        # 如果 oas_data 是 None 或者字符串，走这个保底逻辑
        oas_section = "⚠️ OAS 监控数据暂时无法获取 (FRED API 延迟或配置错误)\n"

    # 4. 这里的逻辑可以对接你的 Gemini 分析模块
    # ai_analysis = call_gemini(report_header + yield_section + oas_section) 
    
    final_report = report_header + yield_section + oas_section
    
    # 5. 推送
    send_telegram_report(final_report)
    print("✅ 任务完成，报告已推送。")

if __name__ == "__main__":
    main()
