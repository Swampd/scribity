from pathlib import Path
from unittest import mock

import scribity_server as server
from parse_drr import parse_mdx_file
from test_scribity_server import ScribityServerTestCase
from test_drr_compatibility import GOOD


class ReportPersistenceTests(ScribityServerTestCase):
    def setUp(self):
        super().setUp()
        self.report_path = self.write_text('report.mdx', GOOD)
        self.result = parse_mdx_file(self.report_path)
        self.client.get('/api/data')

    def payload(self, result=None):
        result = result or self.result
        return self.append_payload(result['items'], result['sources'],
                                   selected_path=self.report_path,
                                   can_import=result.get('can_import'),
                                   diagnostics=result.get('diagnostics', []),
                                   imported_sources=result['sources'])

    def state(self):
        return (server.ITEMS_PATH, server.SOURCES_PATH,
                server.current_document_state('items'), server.current_document_state('sources'))

    def test_import_edit_save_reopen_and_episode_export_preserve_report_metadata(self):
        response = self.client.post('/api/save_import_document', json=self.payload())
        self.assertEqual(response.status_code, 200, response.json)
        fresh = self.client.get('/api/data').json
        self.assertIn('report_provenance', fresh['items'][0])
        fresh['items'][0].update(id_script=8, script_notes='My episode notes')
        saved = self.client.post('/api/save_items', json=self.versioned_payload('items', fresh['items']))
        self.assertEqual(saved.status_code, 200)
        server.reset_document_state('items')
        server.reset_document_state('sources')
        reopened = self.client.get('/api/data').json
        preview = self.client.post('/api/preview_project', json={
            'items_document': reopened['items_document'], 'sources_document': reopened['sources_document'],
            'scope': 'draft', 'empty_draft': True,
        })
        self.assertEqual(preview.status_code, 200, preview.json)
        exported = self.client.post('/api/save_project', json={
            'preview_token': preview.json['preview_token'],
            'items_path': self.path('episode_items.json'), 'sources_path': self.path('episode_sources.json'),
        })
        self.assertEqual(exported.status_code, 200, exported.json)
        item = server.load_json(self.path('episode_items.json'))[0]
        source = server.load_json(self.path('episode_sources.json'))[0]
        self.assertEqual(item['id_script'], 0)
        self.assertEqual(item['script_notes'], 'My episode notes')
        self.assertEqual(item['event_date_yyyy-mm-dd'], '')
        for record in (item, source):
            provenance = record['report_provenance']
            self.assertEqual(provenance['metadata']['publishedOn'], '2026-10-16')
            self.assertEqual(provenance['metadata']['custom'], {'reviewed': False, 'labels': ['sample', 'compatibility']})
            self.assertEqual(provenance['report_id'], 'sample-history-report')
        self.assertEqual(item['report_provenance'], self.result['items'][0]['report_provenance'])

    def test_incomplete_import_is_rejected_by_both_save_routes(self):
        bad = parse_mdx_file(self.write_text('bad.mdx', GOOD.replace('1901. [1]', '1901. [99]')))
        before = self.state()
        for route in ('save_import_document', 'append_import'):
            response = self.client.post('/api/' + route, json=self.payload(bad))
            self.assertEqual(response.status_code, 422, response.json)
            self.assertEqual(response.json['kind'], 'import_not_ready')
            self.assertEqual(self.state(), before)
            self.assertEqual(server.load_json(server.ITEMS_PATH), [])
        self.assertFalse(Path(self.path('scribity_items.json')).exists())

    def test_record_provenance_blocks_incomplete_save_even_without_preview_diagnostics(self):
        payload = self.payload()
        payload['items'][0]['report_provenance'] = {'import_ready': False}
        payload.pop('diagnostics')
        response = self.client.post('/api/save_import_document', json=payload)
        self.assertEqual(response.status_code, 422)

    def test_same_or_revised_report_cannot_be_appended_over_existing_research(self):
        response = self.client.post('/api/save_import_document', json=self.payload())
        self.assertEqual(response.status_code, 200)
        before = self.state()
        stored = server.load_json(server.ITEMS_PATH)
        for content in (GOOD, GOOD.replace('1901.', '1902.')):
            result = parse_mdx_file(self.write_text('renamed.mdx', content))
            payload = self.payload(result)
            payload['items'] = stored + result['items']
            payload['sources'] = server.load_json(server.SOURCES_PATH)
            response = self.client.post('/api/append_import', json=payload)
            self.assertEqual(response.status_code, 409, response.json)
            self.assertEqual(response.json['kind'], 'report_already_imported')
            self.assertEqual(self.state(), before)
            self.assertEqual(server.load_json(server.ITEMS_PATH), stored)

    def test_stale_import_cannot_switch_active_documents(self):
        payload = self.payload()
        server.reset_document_state('sources')
        before = self.state()
        response = self.client.post('/api/save_import_document', json=payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.state(), before)
        self.assertFalse(Path(self.path('scribity_items.json')).exists())

    def test_second_file_failure_leaves_no_new_pair_and_keeps_active_state(self):
        before = self.state()
        real_link = server.os.link
        def fail_source(source, destination):
            if str(destination).endswith('scribity_sources.json'):
                raise OSError('Simulated second file failure')
            return real_link(source, destination)
        with mock.patch.object(server.os, 'link', side_effect=fail_source):
            response = self.client.post('/api/save_import_document', json=self.payload())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.state(), before)
        self.assertFalse(Path(self.path('scribity_items.json')).exists())
        self.assertFalse(Path(self.path('scribity_sources.json')).exists())

    def test_canceling_picker_leaves_documents_and_files_untouched(self):
        before = self.state()
        with mock.patch.object(server, 'TK_AVAILABLE', True), \
                mock.patch.object(server, 'tk', create=True), \
                mock.patch.object(server, 'filedialog', create=True) as dialogs, \
                mock.patch.object(server.os, 'system'):
            dialogs.askopenfilename.return_value = ''
            response = self.client.post('/api/parse_drr_picker', json={'mode': 'file'})
        self.assertEqual(response.json['status'], 'canceled')
        self.assertEqual(self.state(), before)
        self.assertEqual(server.load_json(server.ITEMS_PATH), [])
        self.assertEqual(server.load_json(server.SOURCES_PATH), [])
        self.assertFalse(Path(self.path('scribity_items.json')).exists())

    def test_import_publication_race_does_not_overwrite_files_created_after_path_selection(self):
        before = self.state()
        real_paths = server.next_available_import_paths
        def create_file_after_selection(selected_path):
            items_path, sources_path = real_paths(selected_path)
            Path(items_path).write_text('[{"id_item":"concurrent-file"}]')
            return items_path, sources_path
        with mock.patch.object(server, 'next_available_import_paths', side_effect=create_file_after_selection):
            response = self.client.post('/api/save_import_document', json=self.payload())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.state(), before)
        self.assertEqual(server.load_json(self.path('scribity_items.json')), [{'id_item': 'concurrent-file'}])
        self.assertFalse(Path(self.path('scribity_sources.json')).exists())
