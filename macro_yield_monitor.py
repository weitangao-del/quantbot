import os
import requests
import time

# --- 环境变量配置区 ---
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MACRO_BOT_TOKEN = os.getenv('MACRO_BOT_TOKEN')
# GEMINI_API_KEY = os.getenv('GEMINI_API_KEY') # 你的 Gemini 密钥保留

def get_original_us_yields():
    """
    恢复原版：使用腾讯财经 API 抓取美债收益率
    """
    yields = {}
    symbols = {'10Y': 'us10Y', '2Y': 'us2Y'}
    
    for label, sym in symbols.items():
        url = f"https://qt.gtimg.cn/q={sym}"
        for attempt in range(3):
            try:
                # 严格遵循你的规范：timeout=30, 直连无代理
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200 and len(resp.text) > 15:
                    parts = resp.text.split('~')
                    if len(parts) > 3:
                        yields[label] = float(parts[3])
                        break  # 成功则跳出重试循环
            except Exception as e:
                print(f"⚠️ {label} 抓取重试 ({attempt+1}/3): {e}")
            time.sleep(2) # 错峰延迟
            
    return yields

def send_telegram_alert(text):
    """
    恢复原版：JSON Payload 推送 TG，突破长度限制
    """
    if not MACRO_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TG 配置缺失")
        return
        
    url = f"https://api.telegram.org/bot{MACRO_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=30)
    except Exception as e:
        print(f"❌ TG 发送失败: {e}")

def main():
    print("🔄 执行系统回滚，启动原版美债监控...")
    
    # 1. 抓取国债数据
    yield_data = get_original_us_yields()
    y10 = yield_data.get('10Y', '获取失败')
    y2 = yield_data.get('2Y', '获取失败')
    
    # 2. 倒挂计算容错
    inv_val = "N/A"
    if isinstance(y10, float) and isinstance(y2, float):
        inv_val = round(y10 - y2, 4)

    # 3. 组装最基础的研报
    report = (
        "🏛 **美债宏观投研监控 (恢复版)**\n"
        "-------------------------------\n"
        f"📈 **国债收益率:**\n"
        f"- 10Y Yield: `{y10}%` \n"
        f"- 2Y Yield: `{y2}%` \n"
        f"- 倒挂利差: `{inv_val}%` \n"
    )
    
    # --- 你的 Gemini AI 分析模块挂载点 ---
    # ai_analysis = call_gemini(report)
    # final_report = report + "\n\n" + ai_analysis
    
    # 4. 执行推送
    send_telegram_alert(report)
    print("✅ 回滚代码执行完毕，推送已发出。")

if __name__ == "__main__":
    main()
