"""Run QuantBot with a guard that blocks obviously partial snapshots.

This wrapper protects Google Sheet history and Telegram pushes from runs where
most quote-backed assets fail but fixed cash/crypto still produce a small total.
"""

import os

import requests

import portfolio_monitor as monitor


MIN_REFERENCE_AUM = 50000
MIN_ASSET_COUNT = 8
MAX_DROP_RATIO = 0.60

PRIMARY_CRONS_BY_SLOT = {window["slot"]: window["cron"] for window in monitor.SCHEDULE_WINDOWS}

_original_scheduled_record_already_exists = monitor.scheduled_record_already_exists
_original_sync_to_cloud_history = monitor.sync_to_cloud_history


def is_backup_github_schedule(run_slot):
    event_name = os.getenv("GITHUB_EVENT_NAME", monitor.GITHUB_EVENT_NAME).strip()
    event_schedule = os.getenv("GITHUB_EVENT_SCHEDULE", monitor.GITHUB_EVENT_SCHEDULE).strip()
    primary_cron = PRIMARY_CRONS_BY_SLOT.get(run_slot, "")
    return bool(event_name == "schedule" and event_schedule and primary_cron and event_schedule != primary_cron)


def guarded_scheduled_record_already_exists(report_time, run_slot, is_official_report):
    if not monitor.is_automated_slot_run(run_slot):
        return False

    webhook_url = os.getenv("HISTORY_WEBAPP_URL")
    if not webhook_url:
        return False

    try:
        response = requests.get(f"{webhook_url}?view=all&limit=240", timeout=15)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        if is_backup_github_schedule(run_slot):
            print(f"ℹ️ 无法检查定时记录去重状态，GitHub 备用触发将跳过以避免重复写入: {exc}")
            return True
        print(f"⚠️ 无法检查定时记录去重状态，主触发将继续执行本次运行: {exc}")
        return False

    report_date = report_time.strftime("%Y-%m-%d")
    for row in payload.get("history", []):
        if not monitor.row_matches_report_date(row, report_date):
            continue
        if row.get("schedule_slot") == run_slot:
            print(f"ℹ️ {report_date} {run_slot} 已有记录，本次备用触发跳过。")
            return True
        if monitor.row_session_matches_slot(row, run_slot):
            print(f"ℹ️ {report_date} {run_slot} 已有同场次记录，本次备用触发跳过。")
            return True
        if monitor.legacy_row_matches_slot(row, run_slot):
            print(f"ℹ️ {report_date} {run_slot} 已有旧格式记录，本次备用触发跳过。")
            return True
        if is_official_report and monitor.is_truthy(row.get("is_official_report")):
            print(f"ℹ️ {report_date} 已有正式记录，本次备用触发跳过。")
            return True
    return False


def snapshot_quality_issue(total_value, asset_count, previous_total_value):
    if previous_total_value in (None, ""):
        return None

    previous_total = monitor.parse_number(previous_total_value, None)
    if previous_total is None or previous_total < MIN_REFERENCE_AUM:
        return None

    if total_value < previous_total * MAX_DROP_RATIO and asset_count < MIN_ASSET_COUNT:
        return (
            "AUM and asset count collapsed versus the previous snapshot: "
            f"current AUM CNY {total_value:,.2f} with {asset_count} assets, "
            f"previous AUM CNY {previous_total:,.2f}. Refusing to write a likely partial snapshot."
        )

    return None


def latest_cloud_total_value(webhook_url, current_run_id):
    try:
        response = requests.get(f"{webhook_url}?view=all&limit=20", timeout=30)
        response.raise_for_status()
        history_payload = response.json()
    except Exception as exc:
        print(f"⚠️ 无法读取上一条历史记录用于质量校验，将继续执行: {exc}")
        return None

    for row in history_payload.get("history", []):
        run_id = str(row.get("run_id") or row.get("Run_ID") or "")
        if current_run_id and run_id == current_run_id:
            continue
        total = monitor.parse_number(monitor.get_cell(row, "total_value", "Total_Value"), None)
        if total is not None and total > 0:
            return total
    return None


def guarded_sync_to_cloud_history(
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
    if webhook_url and monitor.is_automated_slot_run(run_slot):
        current_run_id = report_time.strftime("%Y%m%d-%H%M%S")
        previous_total = latest_cloud_total_value(webhook_url, current_run_id)
        issue = snapshot_quality_issue(total_value, len(asset_snapshots), previous_total)
        if issue:
            raise RuntimeError(f"❌ 资产快照质量校验失败: {issue}")

    return _original_sync_to_cloud_history(
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
    )


monitor.scheduled_record_already_exists = guarded_scheduled_record_already_exists
monitor.sync_to_cloud_history = guarded_sync_to_cloud_history


if __name__ == "__main__":
    monitor.get_portfolio_status()
