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

_original_sync_to_cloud_history = monitor.sync_to_cloud_history


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


monitor.sync_to_cloud_history = guarded_sync_to_cloud_history


if __name__ == "__main__":
    monitor.get_portfolio_status()
