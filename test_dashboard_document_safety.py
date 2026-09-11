import os
import unittest


class DashboardDocumentSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), "dashboard.html")
        with open(path, "r", encoding="utf-8") as handle:
            cls.dashboard = handle.read()

    def test_direct_saves_send_document_identity_and_revision(self):
        self.assertIn("document_token: originDocument.token", self.dashboard)
        self.assertIn("revision: activeDocument.revision", self.dashboard)

    def test_parser_append_sends_both_document_versions(self):
        self.assertIn("items_document: itemsDocumentRef.current", self.dashboard)
        self.assertIn("sources_document: sourcesDocumentRef.current", self.dashboard)

    def test_file_switches_flush_pending_delayed_saves_first(self):
        self.assertIn("await flushPendingDocumentSaves('items')", self.dashboard)
        self.assertIn("await flushPendingDocumentSaves('sources')", self.dashboard)

    def test_load_errors_preserve_document_identity_for_recovery_actions(self):
        self.assertIn("apiError.itemsDocument = payload?.items_document", self.dashboard)
        self.assertIn("applyDocumentState('items', e.itemsDocument)", self.dashboard)
        self.assertIn("applyDocumentState('sources', e.sourcesDocument)", self.dashboard)

    def test_example_note_timer_is_owned_by_the_document_save_coordinator(self):
        self.assertIn("const exampleNoteSaveTimer = useRef(null)", self.dashboard)
        self.assertIn("noteSaveTimer={exampleNoteSaveTimer}", self.dashboard)


if __name__ == "__main__":
    unittest.main()
