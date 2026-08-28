from pathlib import Path
import unittest


MAIN_WORKFLOW_PATH = Path(".github/workflows/main.yml")
WORKFLOW_PATH = Path(".github/workflows/portfolio-monitor-schedule.yml")


class WorkflowDedupeTest(unittest.TestCase):
    def test_main_workflow_has_no_github_schedule_and_guards_stale_dispatch(self):
        workflow = MAIN_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("  schedule:", workflow)
        self.assertNotIn("github.event.schedule", workflow)
        self.assertIn("Guard stale dispatch slot", workflow)
        self.assertIn("stale_dispatch_skip", workflow)
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
