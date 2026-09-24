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
portfolio_monitor_guarded = importlib.import_module("portfolio_monitor_guarded")


class GuardedScheduledDedupeTest(unittest.TestCase):
    def test_scheduled_run_skips_when_all_dedupe_checks_timeout(self):
        report_time = datetime(2026, 9, 24, 16, 58, tzinfo=ZoneInfo("Asia/Shanghai"))

        with mock.patch.dict(
            os.environ,
            {
                "HISTORY_WEBAPP_URL": "https://example.test/history",
                "GITHUB_EVENT_NAME": "schedule",
                "GITHUB_EVENT_SCHEDULE": "0 4 * * *",
            },
            clear=False,
        ):
            portfolio_monitor.GITHUB_EVENT_NAME = "schedule"
            with mock.patch.object(
                portfolio_monitor_guarded.requests,
                "get",
                side_effect=TimeoutError("timeout"),
            ):
                self.assertTrue(
                    portfolio_monitor_guarded.guarded_scheduled_record_already_exists(
                        report_time,
                        "ad_hoc_1200",
                        False,
                    )
                )


if __name__ == "__main__":
    unittest.main()
