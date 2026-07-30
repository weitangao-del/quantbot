import sqlite3
import os
import csv
import json
import time
from io import StringIO
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import ccxt
import akshare as ak
import yfinance as yf


# ==========================================
# 1. 核心配置区域：按“组合职责”管理资产
# ==========================================
TELEGRAM_TOKEN = os.getenv("MACRO_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CSV_URL = os.getenv("PORTFOLIO_CSV_URL")
REPORT_TIMEZONE = os.getenv("REPORT_TIMEZONE", "Asia/Shanghai")
GITHUB_EVENT_NAME = os.getenv("GITHUB_EVENT_NAME", "").strip()
GITHUB_EVENT_SCHEDULE = os.getenv("GITHUB_EVENT_SCHEDULE", "").strip()
RUN_SLOT_OVERRIDE = os.getenv("RUN_SLOT_OVERRIDE", "").strip()
TRIGGER_SOURCE = os.getenv("TRIGGER_SOURCE", "").strip()

SCHEDULE_WINDOWS = [
    {"slot": "ad_hoc_0000", "hour": 0, "official": False, "session": "午夜资产快照", "cron": "0 16 * * *"},
    {"slot": "ad_hoc_0600", "hour": 6, "official": False, "session": "早盘资产快照", "cron": "0 22 * * *"},
    {"slot": "ad_hoc_1200", "hour": 12, "official": False, "session": "午间资产快照", "cron": "0 4 * * *"},
    {"slot": "official_1800", "hour": 18, "official": True, "session": "晚盘正式结算", "cron": "0 10 * * *"},
]
SCHEDULE_WINDOW_BY_SLOT = {window["slot"]: window for window in SCHEDULE_WINDOWS}

# 顶层资产桶：不要再按市场分，而是按这笔资产在组合里的职责分。
PORTFOLIO_BUCKETS = {
    "BETA_CORE": {
        "target": 0.55,
        "tolerance": 0.07,
        "label": "Beta核心仓",
        "role": "长期复利主引擎：宽基指数、全球股票、核心ETF",
    },
    "ALPHA_SATELLITE": {
        "target": 0.20,
        "tolerance": 0.05,
        "label": "Alpha卫星仓",
        "role": "争取超额收益：个股、行业主题、Crypto、主动基金",
    },
    "DEFENSE": {
        "target": 0.15,
        "tolerance": 0.05,
        "label": "防守仓",
        "role": "降低波动和尾部风险：黄金、债券、低波红利、货币基金",
    },
    "LIQUIDITY": {
        "target": 0.10,
        "tolerance": 0.03,
        "label": "流动性弹药",
        "role": "安全垫与击球区弹药：现金、短债、活期资金",
    },
}

TARGET_WEIGHTS = {key: item["target"] for key, item in PORTFOLIO_BUCKETS.items()}

# 旧分类兼容层：上线后可以保留一段时间，等在线表格完全改完再删除。
LEGACY_CATEGORY_MAP = {
    "US_TECH": "BETA_CORE",
    "CN_HK": "BETA_CORE",
    "CRYPTO": "ALPHA_SATELLITE",
    "GOLD": "DEFENSE",
    "CASH": "LIQUIDITY",
}

# 击球区：只动用 LIQUIDITY 里的资金，不再直接用“现金”旧分类。
STRIKING_ZONES = {
    "BETA_CORE": [
        {
            "name": "美股成长Beta",
            "ticker": "QQQ",
            "drawdowns": [(35, 0.45), (25, 0.25), (15, 0.10)],
        },
        {
            "name": "港股宽基Beta",
            "ticker": "^HSI",
            "drawdowns": [(35, 0.25), (25, 0.15), (15, 0.08)],
        },
    ],
    "ALPHA_SATELLITE": [
        {
            "name": "BTC/Crypto Alpha",
            "ticker": "BTC-USD",
            "drawdowns": [(70, 0.25), (50, 0.15), (30, 0.08)],
        }
    ],
    "DEFENSE": [],
    "LIQUIDITY": [],
}

UP_SYM = "🟩"
DOWN_SYM = "🟥"
FLAT_SYM = "⬜️"


def local_now():
    return datetime.now(ZoneInfo(REPORT_TIMEZONE))


def get_window_by_slot(run_slot):
    return SCHEDULE_WINDOW_BY_SLOT.get(run_slot)


def is_automated_slot_run(run_slot):
    return bool(run_slot and get_window_by_slot(run_slot) and GITHUB_EVENT_NAME in {"schedule", "workflow_dispatch"})


def get_report_session(now, run_slot=None):
    if run_slot:
        window = get_window_by_slot(run_slot)
        if window:
            return window["session"]
    if 5 <= now.hour < 12:
        return "早盘市场汇报"
    if 12 <= now.hour < 19:
        return "晚盘市场汇报"
    return "盘中市场汇报"


def get_due_schedule_window(now):
    due_windows = [window for window in SCHEDULE_WINDOWS if now.hour >= window["hour"]]
    return due_windows[-1] if due_windows else None


def get_schedule_slot(now):
    if RUN_SLOT_OVERRIDE:
        return RUN_SLOT_OVERRIDE
    window = get_due_schedule_window(now)
    if GITHUB_EVENT_NAME in {"schedule", "workflow_dispatch"} and window:
        return window["slot"]
    return f"manual_{now.strftime('%Y%m%d_%H%M%S')}"


def is_official_report_run(now):
    if RUN_SLOT_OVERRIDE:
        window = get_window_by_slot(RUN_SLOT_OVERRIDE)
        return bool(window and window["official"])
    window = get_due_schedule_window(now)
    return bool(GITHUB_EVENT_NAME in {"schedule", "workflow_dispatch"} and window and window["official"])


def scheduled_record_already_exists(report_time, run_slot, is_official_report):
    if not is_automated_slot_run(run_slot):
        return False

    webhook_url = os.getenv("HISTORY_WEBAPP_URL")
    if not webhook_url:
        return False

    try:
        response = requests.get(f"{webhook_url}?view=all&limit=240", timeout=15)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        print(f"⚠️ 无法检查定时记录去重状态，将继续执行本次运行: {e}")
        return False

    report_date = report_time.strftime("%Y-%m-%d")
    for row in payload.get("history", []):
        if not row_matches_report_date(row, report_date):
            continue
        if row.get("schedule_slot") == run_slot:
            print(f"ℹ️ {report_date} {run_slot} 已有记录，本次备用触发跳过。")
            return True
        if row_session_matches_slot(row, run_slot):
            print(f"ℹ️ {report_date} {run_slot} 已有同场次记录，本次备用触发跳过。")
            return True
        if legacy_row_matches_slot(row, run_slot):
            print(f"ℹ️ {report_date} {run_slot} 已有旧格式记录，本次备用触发跳过。")
            return True
        if is_official_report and is_truthy(row.get("is_official_report")):
            print(f"ℹ️ {report_date} 已有正式记录，本次备用触发跳过。")
            return True
    return False


def row_matches_report_date(row, report_date):
    parsed_date = extract_row_local_date(row)
    if parsed_date:
        return parsed_date == report_date
    raw_date = row.get("date") or row.get("Date")
    return str(raw_date or "").strip()[:10] == report_date


def extract_row_local_date(row):
    for key in ("timestamp", "Timestamp", "date", "Date"):
        raw_value = row.get(key)
        if not raw_value:
            continue
        parsed = parse_history_datetime(raw_value)
        if parsed:
            return parsed.astimezone(ZoneInfo(REPORT_TIMEZONE)).strftime("%Y-%m-%d")

    run_id = str(row.get("run_id") or row.get("Run_ID") or "")
    if len(run_id) >= 8 and run_id[:8].isdigit():
        return f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}"
    return None


def parse_history_datetime(value):
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(REPORT_TIMEZONE))
    return parsed


def row_session_matches_slot(row, run_slot):
    window = get_window_by_slot(run_slot)
    if not window:
        return False
    return str(row.get("session") or row.get("Session") or "").strip() == window["session"]


def legacy_row_matches_slot(row, run_slot):
    expected_hours = {
        "ad_hoc_0000": 0,
        "ad_hoc_0600": 6,
        "ad_hoc_1200": 12,
        "official_1800": 18,
        "official_0900": 9,
        "ad_hoc_1500": 15,
        "ad_hoc_2100": 21,
        "ad_hoc_0300": 3,
    }
    expected_hour = expected_hours.get(run_slot)
    if expected_hour is None:
        return False
    return extract_row_hour(row) == expected_hour


def get_schedule_cron(run_slot):
    if GITHUB_EVENT_SCHEDULE:
        return GITHUB_EVENT_SCHEDULE
    window = get_window_by_slot(run_slot)
    if window:
        return window.get("cron", "")
    return ""


def extract_row_hour(row):
    timestamp = row.get("timestamp") or row.get("Timestamp")
    if timestamp:
        parsed = parse_history_datetime(timestamp)
        if parsed:
            return parsed.astimezone(ZoneInfo(REPORT_TIMEZONE)).hour

    run_id = str(row.get("run_id") or row.get("Run_ID") or "")
    if "-" in run_id:
        hour_text = run_id.split("-", 1)[1][:2]
        if hour_text.isdigit():
            return int(hour_text)
    return None


def is_truthy(value):
    if value is True:
        return True
    return str(value).strip().lower() in {"true", "1", "yes"}


# ==========================================
# 2. 核心工具与通信模块
# ==========================================
def normalize_category(raw_category, asset_name):
    cat = (raw_category or "").strip().upper()
    if cat in PORTFOLIO_BUCKETS:
        return cat

    if cat in LEGACY_CATEGORY_MAP:
        mapped = LEGACY_CATEGORY_MAP[cat]
        print(f"ℹ️ {asset_name} 使用旧分类 {cat}，已临时映射到 {mapped}。建议更新在线表格。")
        return mapped

    print(f"⚠️ {asset_name} 的分类 {cat or '空'} 未识别，临时归入 ALPHA_SATELLITE。请修正在线表格。")
    return "ALPHA_SATELLITE"


def as_float(value):
    """兼容 yfinance 在不同版本中返回 scalar / Series / DataFrame 的情况。"""
    try:
        return float(value)
    except TypeError:
        squeezed = value.squeeze() if hasattr(value, "squeeze") else value
        if hasattr(squeezed, "iloc"):
            squeezed = squeezed.iloc[0]
        return float(squeezed)


def get_cell(row, *names, default=""):
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    return default


def parse_number(value, default=0.0):
    if value in (None, ""):
        return default
    cleaned = str(value).strip().replace(",", "").replace("¥", "").replace("$", "")
    cleaned = cleaned.replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return default


def send_telegram_message(report_text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ 未配置 Telegram Token 或 Chat ID，跳过推送。")
        return

    print("\n正在通过 Telegram 发送报告...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    clean_text = report_text.replace("**", "")
    payload = {
        "chat_id": CHAT_ID,
        "text": clean_text,
        "parse_mode": "HTML",
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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            date TEXT PRIMARY KEY,
            total_value REAL,
            daily_profit REAL
        )
    """
    )
    today = local_now().strftime("%Y-%m-%d")
    try:
        cursor.execute(
            """
            INSERT OR REPLACE INTO history (date, total_value, daily_profit)
            VALUES (?, ?, ?)
        """,
            (today, total_value, daily_profit),
        )
        conn.commit()
    except Exception as e:
        print(f"⚠️ 数据库写入失败: {e}")
    finally:
        conn.close()


def build_bucket_snapshot(category_stats, total_market_value):
    bucket_snapshot = {}
    for bucket, cfg in PORTFOLIO_BUCKETS.items():
        value = category_stats[bucket]["value"]
        profit = category_stats[bucket]["profit"]
        weight = value / total_market_value if total_market_value > 0 else 0.0
        diff = weight - cfg["target"]
        bucket_snapshot[bucket] = {
            "label": cfg["label"],
            "value": round(value, 2),
            "profit": round(profit, 2),
            "weight": round(weight, 6),
            "target": cfg["target"],
            "diff": round(diff, 6),
            "status": "OK" if abs(diff) <= cfg["tolerance"] else ("OVERWEIGHT" if diff > 0 else "UNDERWEIGHT"),
        }
    return bucket_snapshot


def cloud_history_has_payload(webhook_url, payload, attempts=3, wait_seconds=5):
    run_id = payload["run_id"]
    report_date = payload["date"]
    run_slot = payload["schedule_slot"]
    is_official_report = payload["is_official_report"]

    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(wait_seconds)
        try:
            response = requests.get(f"{webhook_url}?view=all&limit=240", timeout=30)
            response.raise_for_status()
            history_payload = response.json()
        except Exception as e:
            print(f"⚠️ 第 {attempt} 次写入确认查询失败: {e}")
            continue

        for row in history_payload.get("history", []):
            if str(row.get("run_id") or row.get("Run_ID") or "") == run_id:
                return True
            if not row_matches_report_date(row, report_date):
                continue
            if row.get("schedule_slot") == run_slot:
                return True
            if row_session_matches_slot(row, run_slot):
                return True
            if is_official_report and is_truthy(row.get("is_official_report")):
                return True
    return False


def sync_to_cloud_history(
    total_value,
    daily_profit,
    total_change_pct,
    category_stats,
    asset_snapshots,
    striking_alerts,
    report_session,
    rates,
    report_time,
    run_slot,
    is_official_report,
):
    webhook_url = os.getenv("HISTORY_WEBAPP_URL")
    if not webhook_url:
        print("⚠️ 未配置 HISTORY_WEBAPP_URL，跳过云端同步。")
        return False

    bucket_snapshot = build_bucket_snapshot(category_stats, total_value)
    payload = {
        "date": report_time.strftime("%Y-%m-%d"),
        "timestamp": report_time.isoformat(timespec="seconds"),
        "run_id": report_time.strftime("%Y%m%d-%H%M%S"),
        "schedule_slot": run_slot,
        "schedule_cron": get_schedule_cron(run_slot),
        "github_event_name": GITHUB_EVENT_NAME,
        "append_mode": "portfolio_snapshot_v2",
        "session": report_session,
        "record_type": "official" if is_official_report else "ad_hoc",
        "is_official_report": is_official_report,
        "total_value": round(total_value, 2),
        "daily_profit": round(daily_profit, 2),
        "daily_change_pct": round(total_change_pct, 4),
        "bucket_snapshot": bucket_snapshot,
        "asset_snapshots": asset_snapshots,
        "striking_alerts": striking_alerts,
        "rates": {key: round(value, 6) for key, value in rates.items()},
    }

    for bucket, snapshot in bucket_snapshot.items():
        prefix = bucket.lower()
        payload[f"{prefix}_value"] = snapshot["value"]
        payload[f"{prefix}_profit"] = snapshot["profit"]
        payload[f"{prefix}_weight"] = snapshot["weight"]
        payload[f"{prefix}_diff"] = snapshot["diff"]
        payload[f"{prefix}_status"] = snapshot["status"]

    payload["bucket_snapshot_json"] = json.dumps(bucket_snapshot, ensure_ascii=False)
    payload["asset_snapshots_json"] = json.dumps(asset_snapshots, ensure_ascii=False)
    payload["striking_alerts_json"] = json.dumps(striking_alerts, ensure_ascii=False)

    try:
        response = requests.post(webhook_url, json=payload, timeout=45)
        response_preview = response.text[:500]
        print(f"📨 Google Sheets Web App 返回: HTTP {response.status_code} | {response_preview}")
        if "Success" in response.text:
            print("📈 仓位、盈亏与资产快照已成功同步至 Google Sheets History 表。")
            return True
        else:
            print(f"⚠️ 云端历史同步返回异常: {response.text[:200]}")
    except Exception as e:
        print(f"⚠️ 云端历史同步请求未确认完成: {e}")

    if cloud_history_has_payload(webhook_url, payload):
        print("📈 写入请求未及时返回，但已在 Google Sheets History 中确认到本次记录。")
        return True
    else:
        print("❌ 云端历史同步失败: 未能在 Google Sheets History 中确认本次记录。")
        return False


# ==========================================
# 3. 击球区追踪引擎：基于流动性弹药池
# ==========================================
def check_macro_drawdown(liquidity_value):
    print("📡 正在扫描击球区，并按流动性弹药池测算火力...")
    alerts = []

    if liquidity_value <= 0:
        return ["流动性弹药池为 0，击球区即使触发也无现金可部署。"]

    for bucket, zone_items in STRIKING_ZONES.items():
        for item in zone_items:
            try:
                data = yf.download(item["ticker"], period="1y", progress=False)
                if data.empty:
                    continue

                high_1y = as_float(data["High"].max())
                current = as_float(data["Close"].iloc[-1])
                dd_pct = abs((current - high_1y) / high_1y * 100)

                for zone_pct, liquidity_ratio in item["drawdowns"]:
                    if dd_pct >= zone_pct:
                        deploy_amount = liquidity_value * liquidity_ratio
                        alerts.append(
                            f"🎯 <b>{PORTFOLIO_BUCKETS[bucket]['label']}击球区</b>: "
                            f"{item['name']} 回撤 {dd_pct:.1f}% (触及 {zone_pct}% 防线)。\n"
                            f"   👉 战术指令: 动用流动性弹药 {liquidity_ratio*100:.0f}% "
                            f"(约 ¥{deploy_amount:,.0f})。"
                        )
                        break
            except Exception as e:
                print(f"⚠️ {item['name']} 击球区雷达报错跳过: {e}")

    return alerts


# ==========================================
# 4. 外脑：芒格视角的 Gemini 架构
# ==========================================
def get_ai_summary(report_text, dev_text, alerts_text):
    if not GEMINI_API_KEY:
        return "\n⚠️ AI 智囊未启用：未配置 GEMINI_API_KEY。\n"

    print("🧠 正在呼叫云端 AI 智囊...")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    )

    sys_prompt = (
        "你现在是我私人的『芒格派首席风控官』。你的核心哲学是：忽略短期宏观噪音，"
        "关注资产护城河，严格执行资产配置再平衡策略。\n"
        "我的组合不再按市场地区分类，而是按职责分类：Beta核心仓、Alpha卫星仓、防守仓、流动性弹药。\n"
        "请阅读今日盘面数据、目标仓位偏离度以及击球区警报，给出犀利、冷静、可执行的建议。\n"
        "1. 如果某个资产桶明显超配或低配，要求我执行再平衡。\n"
        "2. 如果击球区警报响起，严格按照系统计算的金额敦促执行，不准自己瞎编。\n"
        "3. 对今日盈亏一句话冷血点评，强调盈亏同源。\n"
        "4. 依据现有持仓和全球流动性与热点，判断组合是否过度冒险或过度保守。"
    )

    full_context = f"【今日盘面】\n{report_text}\n\n【再平衡诊断】\n{dev_text}\n\n【警报】\n{alerts_text}"
    payload = {
        "contents": [{"parts": [{"text": sys_prompt + "\n\n" + full_context}]}],
        "generationConfig": {"maxOutputTokens": 200000},
    }

    try:
        response = requests.post(url, json=payload, timeout=45)
        response.raise_for_status()
        ai_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return f"\n🤖 <b>芒格智囊点评:</b>\n{ai_text.strip()}\n"
    except Exception as e:
        return f"\n⚠️ AI 智囊暂时离线 ({e})\n"


# ==========================================
# 5. 主循环：动态路由与抓取引擎
# ==========================================
def get_portfolio_status():
    report_time = local_now()
    run_slot = get_schedule_slot(report_time)
    if GITHUB_EVENT_NAME == "schedule" and not run_slot:
        print(f"ℹ️ 当前时间 {report_time.strftime('%H:%M')} 不在 00/06/12/18 记录窗口，跳过。")
        return
    automated_slot = run_slot if is_automated_slot_run(run_slot) else None
    report_session = get_report_session(report_time, automated_slot)
    is_official_report = is_official_report_run(report_time)
    if scheduled_record_already_exists(report_time, run_slot, is_official_report):
        return
    print(
        f"🚀 启动跨市场全天候监控引擎 "
        f"({report_time.strftime('%Y-%m-%d %H:%M:%S')} | slot={run_slot})...\n"
    )

    if not CSV_URL:
        print("❌ 致命错误: 未配置 PORTFOLIO_CSV_URL。程序终止。")
        return

    # --- 1. 获取多币种汇率与宏观数据 ---
    macro_results = []
    rates = {"CNY": 1.0, "USD": 7.25, "HKD": 0.93}
    rate_changes = {"USD": 0.0, "HKD": 0.0}

    try:
        for pair, key in [("USDCNY=X", "USD"), ("HKDCNY=X", "HKD")]:
            fx_data = yf.download(pair, period="5d", progress=False)
            if len(fx_data) >= 2:
                current_rate = as_float(fx_data["Close"].iloc[-1])
                prev_rate = as_float(fx_data["Close"].iloc[-2])
                rates[key] = current_rate
                rate_changes[key] = (current_rate - prev_rate) / prev_rate * 100
    except Exception as e:
        print(f"⚠️ 实时汇率通道受阻，启用系统兜底汇率 ({e})")

    usd_trend = UP_SYM if rate_changes["USD"] > 0 else (DOWN_SYM if rate_changes["USD"] < 0 else FLAT_SYM)
    hkd_trend = UP_SYM if rate_changes["HKD"] > 0 else (DOWN_SYM if rate_changes["HKD"] < 0 else FLAT_SYM)
    macro_results.append(
        f"💱 汇率中枢 | USD: {rates['USD']:.4f} {usd_trend} {rate_changes['USD']:+.2f}% | "
        f"HKD: {rates['HKD']:.4f} {hkd_trend} {rate_changes['HKD']:+.2f}%"
    )

    try:
        cg_resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=pax-gold,bitcoin&vs_currencies=usd&include_24hr_change=true",
            timeout=10,
        ).json()

        gold_change = cg_resp["pax-gold"]["usd_24h_change"]
        macro_results.append(
            f"🌍 国际黄金: ${cg_resp['pax-gold']['usd']:,.2f} "
            f"{UP_SYM if gold_change > 0 else DOWN_SYM} {gold_change:+.2f}%"
        )

        btc_change = cg_resp["bitcoin"]["usd_24h_change"]
        macro_results.append(
            f"🌋 比特币 (BTC): ${cg_resp['bitcoin']['usd']:,.2f} "
            f"{UP_SYM if btc_change > 0 else DOWN_SYM} {btc_change:+.2f}%"
        )

        session = requests.Session()
        session.trust_env = False

        for code, name in [("us.IXIC", "纳斯达克"), ("hkHSI", "恒生指数"), ("sh000001", "上证指数")]:
            resp = session.get(f"http://qt.gtimg.cn/q={code}", timeout=5)
            if "v_" in resp.text:
                parts = resp.text.split("~")
                macro_results.append(
                    f"🏛️ {name}: {float(parts[3]):,.2f} "
                    f"{UP_SYM if float(parts[32]) > 0 else DOWN_SYM} {float(parts[32]):+.2f}%"
                )
    except Exception as e:
        macro_results.append(f"⚠️ 宏观获取失败: {e}")
        session = requests.Session()
        session.trust_env = False

    # --- 2. 拉取云端表格并路由计算 ---
    total_market_value = 0.0
    total_daily_profit = 0.0
    category_stats = {k: {"value": 0.0, "profit": 0.0} for k in PORTFOLIO_BUCKETS.keys()}
    results = []
    asset_snapshots = []

    try:
        csv_resp = requests.get(CSV_URL, timeout=15)
        csv_resp.raise_for_status()
        csv_resp.encoding = "utf-8-sig"
        if "<html" in csv_resp.text[:500].lower():
            raise ValueError("PORTFOLIO_CSV_URL 返回了网页内容，请确认它是公开 CSV 链接。")

        reader = csv.DictReader(StringIO(csv_resp.text))
        fieldnames = {str(name).strip().lower() for name in (reader.fieldnames or [])}
        required_fields = {"asset_id", "quantity"}
        if not required_fields.issubset(fieldnames):
            raise ValueError(
                "在线持仓表缺少 Asset_ID 或 Quantity 列，请检查 Google Sheet 发布的 CSV 范围。"
            )

        exchange = ccxt.mexc()

        for row_number, row in enumerate(reader, start=2):
            asset_id = str(get_cell(row, "Asset_ID", "asset_id")).strip()
            if not asset_id:
                continue

            asset_name = str(get_cell(row, "Asset_Name", "asset_name", default=asset_id)).strip() or asset_id
            qty = parse_number(get_cell(row, "Quantity", "quantity"), None)
            if qty is None:
                print(f"⚠️ 第 {row_number} 行 {asset_name} 的 Quantity 无法识别，已跳过。")
                continue

            cat = normalize_category(get_cell(row, "Category", "category"), asset_name)
            source = str(get_cell(row, "Data_Source", "source", default="FIXED")).strip().upper()
            currency = str(get_cell(row, "Currency", "currency", default="CNY")).strip().upper() or "CNY"

            val_local = 0.0
            profit_local = 0.0
            change_pct = 0.0

            try:
                if source in {"FIXED", "MANUAL", "CASH"}:
                    val_local = qty
                    profit_local = 0.0
                    change_pct = 0.0

                elif asset_id.startswith("f") or source in {"AKSHARE_FUND", "FUND"}:
                    clean_code = asset_id.replace("f", "")
                    fund_data = ak.fund_open_fund_info_em(symbol=clean_code, indicator="单位净值走势")
                    if not fund_data.empty:
                        price = fund_data["单位净值"].iloc[-1]
                        val_local = price * qty
                        try:
                            change_pct = float(str(fund_data["日增长率"].iloc[-1]).replace("%", ""))
                            profit_local = val_local - (val_local / (1 + change_pct / 100))
                        except Exception:
                            pass
                    else:
                        raise Exception("Akshare 未返回数据")

                elif source in {"YFINANCE", "YAHOO", "YAHOO_FINANCE"}:
                    yf_data = yf.download(asset_id, period="5d", progress=False)
                    if yf_data.empty:
                        raise Exception("YFinance 未返回数据")
                    price = as_float(yf_data["Close"].iloc[-1])
                    prev_price = as_float(yf_data["Close"].iloc[-2]) if len(yf_data) >= 2 else price
                    change_pct = ((price - prev_price) / prev_price * 100) if prev_price else 0.0
                    val_local = price * qty
                    profit_local = val_local - (val_local / (1 + change_pct / 100)) if change_pct != 0 else 0

                elif source == "TENCENT":
                    resp = session.get(f"http://qt.gtimg.cn/q={asset_id}", timeout=5)
                    resp.encoding = "gbk"
                    if "v_" in resp.text:
                        parts = resp.text.split("~")
                        price = float(parts[3])
                        change_pct = float(parts[32])
                        val_local = price * qty
                        profit_local = val_local - (val_local / (1 + change_pct / 100)) if change_pct != 0 else 0

                elif source in {"CCXT_MEXC", "CCXT", "MEXC"}:
                    ticker = exchange.fetch_ticker(asset_id)
                    price = ticker["last"]
                    change_pct = parse_number(ticker.get("percentage"), 0.0)
                    val_local = price * qty
                    profit_local = val_local - (val_local / (1 + change_pct / 100)) if change_pct != 0 else 0
                    currency = "USD"

                else:
                    raise Exception(f"未知 Data_Source: {source}")

                conv_rate = rates.get(currency, 1.0)
                val_cny = val_local * conv_rate
                profit_cny = profit_local * conv_rate

                category_stats[cat]["value"] += val_cny
                category_stats[cat]["profit"] += profit_cny
                total_market_value += val_cny
                total_daily_profit += profit_cny

                trend = UP_SYM if change_pct > 0 else (DOWN_SYM if change_pct < 0 else FLAT_SYM)
                bucket_label = PORTFOLIO_BUCKETS[cat]["label"]
                asset_snapshots.append(
                    {
                        "asset_id": asset_id,
                        "asset_name": asset_name,
                        "bucket": cat,
                        "bucket_label": bucket_label,
                        "source": source,
                        "currency": currency,
                        "quantity": qty,
                        "local_value": round(val_local, 2),
                        "cny_value": round(val_cny, 2),
                        "daily_profit": round(profit_cny, 2),
                        "daily_change_pct": round(change_pct, 4),
                    }
                )
                if currency != "CNY":
                    results.append(
                        f"[{bucket_label}] {asset_name}: {currency} {val_local:,.2f} "
                        f"(折¥{val_cny:,.2f}) {trend} {change_pct:+.2f}%"
                    )
                else:
                    results.append(f"[{bucket_label}] {asset_name}: ¥{val_cny:,.2f} {trend} {change_pct:+.2f}%")

            except Exception as e:
                print(f"⚠️ {asset_name} 抓取异常: {e}")
                results.append(f"❌ [{PORTFOLIO_BUCKETS[cat]['label']}] {asset_name}: 抓取失败，已跳过 ({source})")

    except Exception as e:
        print(f"❌ 云端表格读取失败: {e}")
        return

    if not asset_snapshots or total_market_value <= 0:
        print("❌ 本次没有得到有效资产数据，已停止推送和写表，避免污染历史记录。")
        return

    # --- 3. 核心再平衡逻辑测算 ---
    dev_lines = ["\n⚖️ <b>资产职责桶偏离度诊断:</b>"]
    for cat, cfg in PORTFOLIO_BUCKETS.items():
        actual_val = category_stats[cat]["value"]
        actual_ratio = actual_val / total_market_value if total_market_value > 0 else 0
        target = cfg["target"]
        tolerance = cfg["tolerance"]
        diff = actual_ratio - target
        rebalance_amount = abs(diff) * total_market_value

        if abs(diff) <= tolerance:
            status_text = "✅ 区间内"
        elif diff > 0:
            status_text = f"🔴 超配，建议减仓约 ¥{rebalance_amount:,.0f}"
        else:
            status_text = f"🟢 低配，建议补仓约 ¥{rebalance_amount:,.0f}"

        dev_lines.append(
            f"▫️ {cfg['label']} ({cat}): 实际 {actual_ratio*100:>4.1f}% | "
            f"目标 {target*100:>4.1f}% | 容忍 ±{tolerance*100:.0f}% | "
            f"偏离 {diff*100:>+5.1f}% {status_text}"
        )
    dev_text = "\n".join(dev_lines)

    # --- 4. 击球区狙击预警 ---
    liquidity_value = category_stats["LIQUIDITY"]["value"]
    striking_alerts = check_macro_drawdown(liquidity_value)
    alerts_text = "\n".join(striking_alerts) if striking_alerts else "当前未触发击球区，保持流动性弹药耐心等待。"

    # --- 5. 终极拼装与发送 ---
    total_change_pct = (
        (total_daily_profit / (total_market_value - total_daily_profit)) * 100
        if (total_market_value - total_daily_profit) > 0
        else 0.0
    )
    total_trend = UP_SYM if total_daily_profit > 0 else (DOWN_SYM if total_daily_profit < 0 else FLAT_SYM)

    report_lines = [
        f"🏆 <b>私人资管引擎 | {report_session}</b>",
        f"🕒 {report_time.strftime('%Y-%m-%d %H:%M')} {REPORT_TIMEZONE} | 运行于 GitHub Actions",
        "========================================",
    ]
    if TRIGGER_SOURCE:
        report_lines.insert(1, f"🧭 触发来源: {TRIGGER_SOURCE}")
    report_lines.append("🌐 <b>全球宏观风向标</b>")
    report_lines.extend(macro_results)
    report_lines.append("----------------------------------------")
    report_lines.append("🧭 <b>组合职责定义</b>")
    for key, cfg in PORTFOLIO_BUCKETS.items():
        report_lines.append(f"▫️ {cfg['label']} ({key}): {cfg['role']}")
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
    report_lines.append(f"🔥 <b>实盘波动盈亏: {total_trend} ¥ {total_daily_profit:,.2f} ({total_change_pct:+.2f}%)</b>")

    final_report = "\n".join(report_lines)
    save_daily_snapshot(total_market_value, total_daily_profit)

    ai_comment = get_ai_summary(final_report, dev_text, alerts_text)
    final_report += ai_comment

    print(final_report)
    sync_ok = sync_to_cloud_history(
        total_market_value,
        total_daily_profit,
        total_change_pct,
        category_stats,
        asset_snapshots,
        striking_alerts,
        report_session,
        rates,
        report_time,
        run_slot,
        is_official_report,
    )
    if sync_ok:
        final_report += "\n📊 表格同步: 已写入 Google Sheets。"
    else:
        final_report += "\n⚠️ 表格同步: 未确认写入 Google Sheets，请检查 HISTORY_WEBAPP_URL 或 Apps Script 部署。"
    send_telegram_message(final_report)


if __name__ == "__main__":
    get_portfolio_status()
