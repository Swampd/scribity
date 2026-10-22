import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import scribity_server as s
from project_document import new_project, write_project, load_project


class UnifiedProjectAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(s, 'PROJECT_PATH', None),
                        patch.object(s, 'PROJECT_DOCUMENT', {'token': 'project-start', 'revision': 0}),
                        patch.object(s, 'ITEMS_PATH', str(self.root / 'items.json')),
                        patch.object(s, 'SOURCES_PATH', str(self.root / 'sources.json')),
                        patch.object(s, 'ITEMS_DOCUMENT', {'token': 'items', 'revision': 0}),
                        patch.object(s, 'SOURCES_DOCUMENT', {'token': 'sources', 'revision': 0}),
                        patch.object(s, 'ITEMS_READY', True), patch.object(s, 'SOURCES_READY', True),
                        patch.object(s, 'CONFIG_PATH', str(self.root / 'config.json')),
                        patch.object(s, 'TK_AVAILABLE', False), patch.object(s, 'PROJECT_PREVIEWS', {})]
        for patcher in self.patches:
            patcher.start(); self.addCleanup(patcher.stop)
        self.items = [{'id_item': 'p', 'id_source': 's', 'id_script': 7, 'metadata': {'keep': True}},
                      {'id_item': 'c', 'nested_under': 'p', 'id_script': 0, 'script_notes': 'support'}]
        self.sources = [{'id_source': 's', 'title': 'Evidence', 'url': ''}, {'id_source': 'unused'}]
        Path(s.ITEMS_PATH).write_text(json.dumps(self.items))
        Path(s.SOURCES_PATH).write_text(json.dumps(self.sources))
        self.client = s.app.test_client()

    def tokens(self):
        return {name + '_document': s.current_document_state(name) for name in ('items', 'sources')}

    def action(self, operation, **values):
        return self.client.post('/api/project/action', json={**self.tokens(), 'operation': operation, **values})

    def convert(self):
        response = self.action('convert', use_current=True, path=str(self.root / 'project.json'))
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['status'], 'success')
        return response.json

    def test_conversion_open_save_and_reopen_preserve_metadata_and_originals(self):
        originals = [Path(s.ITEMS_PATH).read_bytes(), Path(s.SOURCES_PATH).read_bytes()]
        opened = self.convert()
        self.assertEqual(opened['items'], self.items)
        self.assertEqual(opened['sources'], self.sources)
        self.assertEqual(opened['items_document'], opened['sources_document'])
        path = s.PROJECT_PATH
        doc = load_project(path); doc['extra'] = {'keep': [1, 'two']}; write_project(path, doc)
        updated = copy.deepcopy(self.items); updated[0]['script_notes'] = 'new note'
        saved = self.client.post('/api/project/save', json={**self.tokens(), 'items': updated, 'sources': self.sources})
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(load_project(path)['extra'], doc['extra'])
        self.assertEqual(load_project(path)['items'], updated)
        reopened = self.action('open', path=path)
        self.assertEqual(reopened.json['items'], updated)
        self.assertEqual(self.client.get('/api/data').json['project']['path'], path)
        self.assertEqual([Path(s.ITEMS_PATH).read_bytes(), Path(s.SOURCES_PATH).read_bytes()], originals)

    def test_cancel_invalid_open_config_failure_and_stale_save_keep_active_project(self):
        self.convert(); path = s.PROJECT_PATH; before = Path(path).read_bytes(); tokens = self.tokens()
        self.assertEqual(self.action('open', path='').json['status'], 'canceled')
        bad = self.root / 'bad.json'; bad.write_text('{}')
        self.assertEqual(self.action('open', path=str(bad)).status_code, 422)
        other = self.root / 'other.json'; write_project(str(other), new_project('Other', [], []))
        with patch.object(s, 'save_json', side_effect=OSError('config failure')):
            self.assertEqual(self.action('open', path=str(other)).status_code, 500)
        self.assertEqual(s.PROJECT_PATH, path)
        self.assertEqual(self.tokens(), tokens)
        stale = {**tokens, 'items_document': {'token': 'old', 'revision': 0}}
        response = self.client.post('/api/project/save', json={**stale, 'items': [], 'sources': []})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Path(path).read_bytes(), before)

    def test_save_as_preserves_identity_and_rejects_existing_files_or_legacy_originals(self):
        self.convert(); old = s.PROJECT_PATH; identity = load_project(old)['project_id']
        self.assertEqual(self.action('save_as', path=old).status_code, 422)
        self.assertEqual(self.action('save_as', path=s.ITEMS_PATH).status_code, 422)
        response = self.action('save_as', path=str(self.root / 'copy.json'))
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(load_project(s.PROJECT_PATH)['project_id'], identity)
        self.assertNotEqual(s.PROJECT_PATH, old)

    def test_new_project_and_legacy_writes_cannot_split_active_project(self):
        response = self.action('new', path=str(self.root / 'empty.json'), mode='research')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['items'], [])
        self.assertEqual(response.json['project']['schema_mode'], 'research')
        for endpoint in ('save_items', 'save_sources', 'switch_items', 'open_sources', 'new_document'):
            self.assertEqual(self.client.post('/api/' + endpoint, json={}).status_code, 409)

    def test_selection_exports_one_file_with_recursive_support_and_empty_draft(self):
        self.convert(); original = s.PROJECT_PATH
        preview = self.client.post('/api/preview_project', json={**self.tokens(), 'scope': 'draft'}).json
        self.assertEqual(preview['counts']['total'], 2)
        target = str(self.root / 'episode.json')
        response = self.client.post('/api/save_project', json={
            'preview_token': preview['preview_token'], 'single_file': True, 'path': target})
        self.assertEqual(response.status_code, 200, response.json)
        doc = load_project(target)
        self.assertEqual([item['id_script'] for item in doc['items']], [0, 0])
        self.assertEqual(doc['items'][1]['nested_under'], 'p')
        self.assertEqual(len(doc['sources']), 1)
        self.assertEqual(s.PROJECT_PATH, original)
        opened = self.client.post('/api/open_project', json={**self.tokens(), 'project_token': response.json['project_token']})
        self.assertEqual(opened.status_code, 200, opened.json)
        self.assertEqual(s.PROJECT_PATH, target)

    def test_selection_can_preserve_draft_order_and_project_metadata(self):
        self.convert()
        doc = load_project(s.PROJECT_PATH); doc['custom'] = {'lineage': [1, 2]}
        write_project(s.PROJECT_PATH, doc)
        preview = self.client.post('/api/preview_project', json={
            **self.tokens(), 'scope': 'checked', 'selected_ids': ['p'], 'empty_draft': False}).json
        target = str(self.root / 'ordered.json')
        saved = self.client.post('/api/save_project', json={
            'preview_token': preview['preview_token'], 'single_file': True, 'path': target})
        self.assertEqual(saved.status_code, 200, saved.json)
        extracted = load_project(target)
        self.assertEqual([i['id_script'] for i in extracted['items']], [7, 0])
        self.assertEqual(extracted['custom'], doc['custom'])
        self.assertNotEqual(extracted['project_id'], doc['project_id'])

    def test_native_cancel_and_document_change_while_dialog_open_do_not_create_files(self):
        self.convert(); original = s.PROJECT_PATH
        root, dialogs = MagicMock(), MagicMock()
        with patch.object(s, 'TK_AVAILABLE', True), patch.object(s, 'tk', root, create=True), patch.object(s, 'filedialog', dialogs, create=True):
            dialogs.asksaveasfilename.return_value = ''
            self.assertEqual(self.action('save_as').json['status'], 'canceled')
            target = str(self.root / 'stale.json')
            def switched(**kwargs):
                s.PROJECT_DOCUMENT['revision'] += 1
                return target
            dialogs.asksaveasfilename.side_effect = switched
            self.assertEqual(self.action('save_as').status_code, 409)
        self.assertEqual(s.PROJECT_PATH, original)
        self.assertFalse(Path(target).exists())

    def test_failed_autosave_keeps_file_and_revision_intact(self):
        self.convert(); before = Path(s.PROJECT_PATH).read_bytes(); state = self.tokens()
        with patch('project_document.os.replace', side_effect=OSError('disk failure')):
            response = self.client.post('/api/project/save', json={**state, 'items': [], 'sources': []})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(Path(s.PROJECT_PATH).read_bytes(), before)
        self.assertEqual(self.tokens(), state)

    def test_import_creates_one_project_and_append_saves_both_lists_together(self):
        self.convert()
        imported_item = {'id_item': 'imported', 'id_source': 'imported-source', 'category_part_name': ['Topic'],
                         'report_provenance': {'report_id': 'report-1', 'import_ready': True, 'metadata': {'publishedOn': '2026-10-16'}}}
        imported_source = {'id_source': 'imported-source', 'title': 'Citation', 'report_provenance': {'report_id': 'report-1', 'import_ready': True}}
        payload = {**self.tokens(), 'items': [imported_item], 'sources': [imported_source],
                   'can_import': True, 'diagnostics': [], 'single_file': True, 'selected_path': str(self.root)}
        saved = self.client.post('/api/save_import_document', json=payload)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertTrue(saved.json.get('project'))
        self.assertEqual(load_project(s.PROJECT_PATH)['items'], [imported_item])
        self.assertEqual(saved.json['project']['schema_mode'], 'research')
        appended = self.client.post('/api/append_import', json={**self.tokens(), 'can_import': True, 'diagnostics': [],
            'items': [imported_item, {'id_item': 'additional', 'id_source': 'new-source'}],
            'sources': [imported_source, {'id_source': 'new-source', 'title': 'New'}],
            'imported_sources': [{'id_source': 'new-source', 'title': 'New'}]})
        self.assertEqual(appended.status_code, 200, appended.json)
        self.assertEqual(len(load_project(s.PROJECT_PATH)['items']), 2)
        self.assertEqual(len(load_project(s.PROJECT_PATH)['sources']), 2)
        self.assertEqual(appended.json['items_document'], appended.json['sources_document'])

    def test_conversion_infers_research_mode_and_reports_broken_links_without_repair(self):
        raw = [{'id_item': 'research', 'category_part_name': ['History'], 'id_source': 'missing', 'notes': {'opaque': True}}]
        Path(s.ITEMS_PATH).write_text(json.dumps(raw))
        opened = self.convert()
        self.assertEqual(opened['project']['schema_mode'], 'research')
        self.assertEqual(opened['items'], raw)
        self.assertTrue(any('missing' in notice for notice in opened['notices']))

    def test_next_start_configuration_restores_the_single_project_path(self):
        self.convert(); expected = s.PROJECT_PATH
        self.assertEqual(json.loads(Path(s.CONFIG_PATH).read_text()), {'project_path': expected})
        s.PROJECT_PATH = None
        s.restore_last_used_paths()
        self.assertEqual(s.PROJECT_PATH, expected)
        self.assertEqual(self.client.get('/api/data').json['items'], self.items)


if __name__ == '__main__':
    unittest.main()
