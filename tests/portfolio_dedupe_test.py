import importlib
import os
import sys
import types
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest import mock
import unittest


for module_name in ("akshare", "ccxt", "yfinance"):
    sys.modules.setdefault(module_name, types.SimpleNamespace())
sys.modules.setdefault("requests", types.SimpleNamespace(get=lambda *args, **kwargs: None))

portfolio_monitor = importlib.import_module("portfolio_monitor")


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "history": [
                {
                    "run_id": "20260727-011523",
                    "timestamp": "2026-07-27T01:15:23+08:00",
                    "date": "2026-07-26T16:00:00.000Z",
                    "session": "午夜资产快照",
                    "record_type": "ad_hoc",
                    "is_official_report": False,
                }
            ]
        }


class ScheduledDedupeTest(unittest.TestCase):
    def test_delayed_midnight_retry_detects_existing_snapshot_without_schedule_slot(self):
        report_time = datetime(2026, 7, 27, 1, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

        with mock.patch.dict(
            os.environ,
            {
                "HISTORY_WEBAPP_URL": "https://example.test/history",
                "GITHUB_EVENT_NAME": "schedule",
            },
            clear=False,
        ):
            portfolio_monitor.GITHUB_EVENT_NAME = "schedule"
            portfolio_monitor.RUN_SLOT_OVERRIDE = ""
            with mock.patch.object(portfolio_monitor.requests, "get", return_value=FakeResponse()):
                self.assertTrue(
                    portfolio_monitor.scheduled_record_already_exists(
                        report_time,
                        "ad_hoc_0000",
                        False,
                    )
                )
