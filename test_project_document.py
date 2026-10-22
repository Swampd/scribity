import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import project_document as p


class ProjectDocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'project.json')
        self.items = [{'id_item': 'parent', 'id_source': 'source', 'id_script': 4,
                       'custom': {'nested': ['keep']}, 'script_notes': 'notes'},
                      {'id_item': 'child', 'nested_under': 'parent', 'id_script': 0}]
        self.sources = [{'id_source': 'source', 'url': '', 'title': 'Unresolved',
                         'report_provenance': {'publication_date': '2026-10-16'}}]

    def test_round_trip_preserves_all_record_and_project_metadata(self):
        document = p.new_project('Improv', self.items, self.sources, 'improv')
        document['custom_project_metadata'] = {'values': [False, None, 1]}
        original = copy.deepcopy(document)
        p.write_project(self.path, document, new=True)
        loaded = p.load_project(self.path)
        self.assertEqual(loaded, original)
        self.assertEqual(document, original)
        self.assertEqual(loaded['items'], self.items)

    def test_new_file_never_overwrites_and_failed_write_leaves_original(self):
        document = p.new_project('One', self.items, self.sources)
        p.write_project(self.path, document, new=True)
        with self.assertRaises(FileExistsError):
            p.write_project(self.path, document, new=True)
        before = Path(self.path).read_bytes()
        with patch.object(p.os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                p.write_project(self.path, p.new_project('Two', [], []))
        self.assertEqual(Path(self.path).read_bytes(), before)
        self.assertEqual(os.listdir(self.tmp.name), ['project.json'])

    def test_unknown_version_and_ambiguous_ids_are_rejected(self):
        doc = p.new_project('Valid', self.items, self.sources)
        for updates in ({'version': 2}, {'version': True}, {'items': {}},
                        {'items': [{'id_item': 'x'}, {'id_item': 'x'}]},
                        {'sources': [{'title': 'Missing ID'}]}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                p.validate_project({**doc, **updates})

    def test_unlinked_items_are_valid_but_broken_links_are_reported_not_changed(self):
        doc = p.new_project('Links', [
            {'id_item': 'unlinked', 'id_source': ''},
            {'id_item': 'orphan', 'id_source': 'missing', 'nested_under': 'gone'},
            {'id_item': 'cycle1', 'nested_under': 'cycle2'},
            {'id_item': 'cycle2', 'nested_under': 'cycle1'},
        ], [])
        before = copy.deepcopy(doc)
        notices = p.relationship_notices(doc)
        self.assertTrue(any('missing' in notice for notice in notices))
        self.assertTrue(any('gone' in notice for notice in notices))
        self.assertTrue(any('cycle' in notice.lower() for notice in notices))
        self.assertFalse(any('unlinked' in notice for notice in notices))
        self.assertEqual(doc, before)


if __name__ == '__main__':
    unittest.main()
