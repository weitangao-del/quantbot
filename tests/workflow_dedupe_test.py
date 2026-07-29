from pathlib import Path
import unittest


WORKFLOW_PATH = Path(".github/workflows/portfolio-monitor-schedule.yml")


class WorkflowDedupeTest(unittest.TestCase):
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
