import os
import unittest


class DashboardDocumentSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), "dashboard.html")
        with open(path, "r", encoding="utf-8") as handle:
            cls.dashboard = handle.read()

    def assertContains(self, text):
        self.assertTrue(text in self.dashboard, f"Missing document-session safeguard: {text}")

    def test_item_document_activation_clears_old_history_and_item_scoped_ui(self):
        for text in (
            "const resetItemsDocumentSession =",
            "undoStack.current = []",
            "redoStack.current = []",
            "inspectorUndoSnapshot.current = null",
            "setSelectedItemId(null)",
            "setBulkSelectedIds(new Set())",
            "setSelectedRule('__all__')",
            "setStageRule(null)",
            "setDeleteToast(null)",
        ):
            self.assertContains(text)

    def test_source_document_activation_does_not_discard_item_undo_history(self):
        self.assertContains("const resetSourcesDocumentSession =")
        self.assertContains("resetSaveQueueForActivation(sourcesSaveQueue)")
        self.assertContains("setSelectedSourceId(null)")
        source_reset_start = self.dashboard.index("const resetSourcesDocumentSession =")
        source_reset_end = self.dashboard.index("const activateItemsDocument =", source_reset_start)
        source_reset = self.dashboard[source_reset_start:source_reset_end]
        self.assertNotIn("undoStack.current", source_reset)

    def test_successful_open_and_create_paths_use_central_activation(self):
        self.assertGreaterEqual(self.dashboard.count("activateItemsDocument({"), 4)
        self.assertGreaterEqual(self.dashboard.count("activateSourcesDocument({"), 4)
        self.assertContains("const activateItemsDocument =")
        self.assertContains("const activateSourcesDocument =")

    def test_undo_refuses_history_from_a_different_document_identity(self):
        self.assertContains("itemsHistoryDocumentToken.current !== itemsDocumentRef.current.token")
        self.assertContains("itemsHistoryDocumentToken.current = document.token")

    def test_save_as_keeps_same_document_history_bound_to_the_new_identity(self):
        self.assertContains("itemsHistoryDocumentToken.current = json.document.token")

    def test_late_save_response_cannot_restore_a_previous_document_identity(self):
        self.assertContains("activeJob.documentRef.current.token !== activeJob.originDocument.token")


if __name__ == "__main__":
    unittest.main()
