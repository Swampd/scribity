import os
import unittest


class DashboardAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), "dashboard.html")
        with open(path, "r", encoding="utf-8") as handle:
            cls.dashboard = handle.read()

    def test_example_flags_use_native_checkboxes(self):
        self.assertGreaterEqual(self.dashboard.count('type="checkbox"'), 2)
        self.assertIn('checked={Boolean(item.contains_only_example)}', self.dashboard)
        self.assertIn('checked={Boolean(item.contains_example)}', self.dashboard)

    def test_panel_resizers_expose_separator_semantics_and_keyboard_controls(self):
        self.assertGreaterEqual(self.dashboard.count('role="separator"'), 2)
        self.assertIn('aria-valuenow={sidebarWidth}', self.dashboard)
        self.assertIn('aria-valuenow={stageWidth}', self.dashboard)
        for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
            self.assertIn(f"case '{key}':", self.dashboard)

    def test_stage_cards_have_keyboard_reorder_actions(self):
        self.assertIn('aria-label={`Move item ${idx + 1} up`}', self.dashboard)
        self.assertIn('aria-label={`Move item ${idx + 1} down`}', self.dashboard)
        self.assertIn('reorderStageItems(idx, idx - 1)', self.dashboard)
        self.assertIn('reorderStageItems(idx, idx + 1)', self.dashboard)

    def test_library_cards_can_assign_to_the_active_stage_without_dragging(self):
        self.assertIn('aria-label={`Assign item to ${stageRule}', self.dashboard)
        self.assertIn("assignItemToRule(item.id_item, stageRule", self.dashboard)
        self.assertIn('Assign to Stage', self.dashboard)


if __name__ == "__main__":
    unittest.main()
