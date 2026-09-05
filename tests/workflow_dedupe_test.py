from pathlib import Path
import unittest


MAIN_WORKFLOW_PATH = Path(".github/workflows/main.yml")
WORKFLOW_PATH = Path(".github/workflows/portfolio-monitor-schedule.yml")


class WorkflowDedupeTest(unittest.TestCase):
    def test_main_workflow_has_github_schedule_fallback_and_guards_stale_runs(self):
        workflow = MAIN_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("  schedule:", workflow)
        self.assertIn('cron: "0 16 * * *"', workflow)
        self.assertIn('cron: "0 22 * * *"', workflow)
        self.assertIn('cron: "0 4 * * *"', workflow)
        self.assertIn('cron: "0 10 * * *"', workflow)
        self.assertIn("GITHUB_EVENT_SCHEDULE: ${{ github.event.schedule }}", workflow)
        self.assertIn("Guard stale dispatch slot", workflow)
        self.assertIn("schedules = {", workflow)
        self.assertIn("stale_dispatch_skip", workflow)
        self.assertIn("stale_schedule_skip", workflow)
        self.assertIn("official_1800", workflow)
        self.assertIn("18, 19, 20, 21, 22", workflow)

    def test_official_dedupe_validates_existing_row_time_window(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("def row_matches_slot", workflow)
        self.assertIn("row_hour_value in allowed_hours", workflow)
        self.assertIn(
            "if official and truthy(row.get(\"is_official_report\")) and row_matches_slot(row, slot, timezone):",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
