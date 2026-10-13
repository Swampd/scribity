import copy
import json
import os
import unittest
from unittest import mock

import scribity_server as server
from project_extraction import AUDIT_FIELD, build_project
from test_scribity_server import ScribityServerTestCase


def fixture():
    items = [
        {'id_item': 'a', 'id_script': 7, 'id_source': 's1', 'quote_original': 'Context deliberately selected',
         'nested_under': '', 'category_part_name': ['Research'], 'id_subpart': [9],
         'script_part': 'Old part', 'user_02_comments': 'Keep my notes', 'related_facts': ['grp_example'],
         'relevance_tags': ['context'], 'custom': {'future_metadata': [1, 2]}},
        {'id_item': 'b', 'id_script': 0, 'id_source': 's1', 'nested_under': 'a'},
        {'id_item': 'c', 'id_script': 0, 'id_source': 's2', 'nested_under': 'b'},
        {'id_item': 'd', 'id_script': 12, 'id_source': 's2', 'nested_under': ''},
        {'id_item': 'outside', 'id_script': 0, 'id_source': 'unused', 'related_facts': ['grp_example']},
    ]
    sources = [{'id_source': 's1', 'title': 'One', 'custom': {'keep': True}},
               {'id_source': 's2', 'title': 'Two'}, {'id_source': 'unused'}]
    return items, sources


class ProjectBuilderTests(unittest.TestCase):
    def test_recursive_draft_source_dedup_and_lossless_empty_copy(self):
        items, sources = fixture()
        original = copy.deepcopy((items, sources))
        result = build_project(items, sources)
        self.assertEqual(result['counts'], dict(selected=2, supporting=2, total=4, sources=2))
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['warnings'], [])
        for before, after in zip(items, result['items']):
            self.assertEqual(after, {**before, 'id_script': 0})
        self.assertEqual(result['sources'], sources[:2])
        self.assertEqual((items, sources), original)

    def test_preserve_keeps_original_order_and_nonmembership(self):
        items, sources = fixture()
        result = build_project(items, sources, 'checked', ['a', 'outside'], False)
        self.assertEqual([i['id_script'] for i in result['items']], [7, 0, 0, 0])
        self.assertEqual(result['items'], [items[n] for n in [0, 1, 2, 4]])

    def test_filtered_ids_are_exact_and_descendants_counted_once(self):
        result = build_project(*fixture(), 'filtered', ['a', 'b', 'a'])
        self.assertEqual(result['counts'], dict(selected=2, supporting=1, total=3, sources=2))
        self.assertNotIn('d', [i['id_item'] for i in result['items']])

    def test_child_without_parent_detaches_with_provenance_and_keeps_descendants(self):
        result = build_project(*fixture(), 'checked', ['b'])
        child = result['items'][0]
        self.assertEqual(child['nested_under'], '')
        self.assertEqual(child[AUDIT_FIELD][0]['value'], 'a')
        self.assertEqual(result['items'][1]['nested_under'], 'b')
        self.assertEqual(result['counts']['total'], 2)
        self.assertIn('parent outside selection', result['warnings'][0])

    def test_missing_parent_and_external_cross_references_are_explicit(self):
        items, sources = fixture()
        items[0].update(nested_under='missing-parent', supports='outside', contradicts='unknown',
                        related_facts=['grp_example', 'outside', 'd', 'missing-item'])
        result = build_project(items, sources, 'checked', ['a', 'd'])
        first = result['items'][0]
        self.assertEqual(first['nested_under'], '')
        self.assertEqual(first['supports'], '')
        self.assertEqual(first['contradicts'], '')
        self.assertEqual(first['related_facts'], ['grp_example', 'd'])
        self.assertEqual(len(first[AUDIT_FIELD]), 5)
        self.assertNotIn('outside', [i['id_item'] for i in result['items']])
        self.assertEqual(result['errors'], [])

    def test_cycles_self_cycles_and_deep_chains_terminate(self):
        for parents in [('b', 'a'), ('a', 'a')]:
            items = [{'id_item': 'a', 'nested_under': parents[0]}, {'id_item': 'b', 'nested_under': parents[1]}]
            result = build_project(items, [], 'checked', ['a'])
            self.assertTrue(any('cycle' in error for error in result['errors']))
        items = [{'id_item': str(n), 'nested_under': str(n - 1) if n else ''} for n in range(1500)]
        result = build_project(items, [], 'checked', ['0'])
        self.assertEqual(result['counts']['total'], 1500)
        self.assertEqual(result['errors'], [])

    def test_missing_and_conflicting_sources_block_but_identical_duplicates_dedup(self):
        items, sources = fixture()
        self.assertTrue(build_project(items, sources[:1])['errors'])
        self.assertTrue(build_project(items, sources + [{'id_source': 's1', 'title': 'Conflict'}])['errors'])
        dedup = build_project(items, sources + [sources[0]])
        self.assertEqual(dedup['counts']['sources'], 2)
        self.assertEqual(dedup['errors'], [])
        self.assertTrue(dedup['warnings'])

    def test_invalid_selections_and_ambiguous_identities_are_rejected(self):
        items, sources = fixture()
        for scope, ids in [('wrong', []), ('checked', ['gone']), ('filtered', None)]:
            with self.assertRaises(ValueError):
                build_project(items, sources, scope, ids)
        with self.assertRaises(ValueError):
            build_project(items + [items[0]], sources)
        self.assertTrue(build_project(items, sources, 'checked', [])['errors'])

    def test_existing_provenance_and_opaque_metadata_are_retained(self):
        items, sources = fixture()
        items[1][AUDIT_FIELD] = [{'field': 'prior', 'value': 'keep'}]
        items[1]['id_extra_01'] = 'outside'
        result = build_project(items, sources, 'checked', ['b'])
        self.assertEqual(result['items'][0][AUDIT_FIELD][0], items[1][AUDIT_FIELD][0])
        self.assertEqual(result['items'][0]['id_extra_01'], 'outside')
        items[1][AUDIT_FIELD] = 'reserved-field-conflict'
        self.assertTrue(build_project(items, sources, 'checked', ['b'])['errors'])


class ProjectEndpointTests(ScribityServerTestCase):
    def setUp(self):
        super().setUp()
        self.items, self.sources = fixture()
        self.write_json('items.json', self.items)
        self.write_json('sources.json', self.sources)
        self.client.get('/api/data')
        self.previews = mock.patch.object(server, 'PROJECT_PREVIEWS', {})
        self.previews.start()
        self.addCleanup(self.previews.stop)
        self.original = self.active_state()

    def active_state(self):
        return (server.ITEMS_PATH, server.SOURCES_PATH, server.ITEMS_READY, server.SOURCES_READY,
                server.current_document_state('items'), server.current_document_state('sources'))

    def sessions(self):
        return {f'{name}_document': server.current_document_state(name) for name in ('items', 'sources')}

    def preview(self, **kwargs):
        response = self.client.post('/api/preview_project', json={**self.sessions(), **kwargs})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def save(self, preview=None, **kwargs):
        preview = preview or self.preview()
        return self.client.post('/api/save_project', json={
            'preview_token': preview['preview_token'],
            'items_path': self.path('episode_items.json'), 'sources_path': self.path('episode_sources.json'), **kwargs})

    def assert_original_untouched(self):
        self.assertEqual(self.active_state(), self.original)
        self.assertEqual(server.load_json(self.original[0]), self.items)
        self.assertEqual(server.load_json(self.original[1]), self.sources)
        self.assertFalse(os.path.exists(server.CONFIG_PATH))

    def test_preview_save_and_explicit_open_pair(self):
        preview = self.preview()
        self.assertEqual(preview['counts']['total'], 4)
        self.assert_original_untouched()
        saved = self.save(preview)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual([i['id_script'] for i in server.load_json(saved.json['items_path'])], [0, 0, 0, 0])
        self.assert_original_untouched()
        opened = self.client.post('/api/open_project', json={**self.sessions(), 'project_token': saved.json['project_token']})
        self.assertEqual(opened.status_code, 200, opened.json)
        self.assertEqual(server.ITEMS_PATH, saved.json['items_path'])
        self.assertEqual(server.SOURCES_PATH, saved.json['sources_path'])
        self.assertNotEqual(opened.json['items_document']['token'], self.original[4]['token'])
        with open(server.CONFIG_PATH) as config_file:
            self.assertEqual(json.load(config_file)['items_path'], server.ITEMS_PATH)

    def test_preserve_option_api_does_not_draft_all_items(self):
        saved = self.save(self.preview(scope='checked', selected_ids=['a', 'outside'], empty_draft=False))
        self.assertEqual(saved.status_code, 200)
        self.assertEqual([i['id_script'] for i in server.load_json(saved.json['items_path'])], [7, 0, 0, 0])

    def test_cancel_either_dialog_never_writes(self):
        for choices in [[], [self.path('episode_items.json')]]:
            with self.subTest(choices=choices), mock.patch.object(server, 'TK_AVAILABLE', True), \
                    mock.patch.object(server, 'tk', create=True), mock.patch.object(server, 'filedialog', create=True) as dialogs:
                dialogs.asksaveasfilename.side_effect = choices + ['']
                preview = self.preview()
                response = self.client.post('/api/save_project', json={'preview_token': preview['preview_token']})
                self.assertEqual(response.json['status'], 'canceled')
                self.assertEqual(sorted(os.listdir(self.temp_dir.name)), ['items.json', 'sources.json'])
                self.assert_original_untouched()

    def test_second_publish_failure_rolls_back_new_pair(self):
        real_link = os.link
        def fail_sources(source, destination):
            if destination == self.path('episode_sources.json'):
                raise OSError('Simulated second file failure')
            return real_link(source, destination)
        with mock.patch.object(server.os, 'link', side_effect=fail_sources):
            response = self.save()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(sorted(os.listdir(self.temp_dir.name)), ['items.json', 'sources.json'])
        self.assert_original_untouched()

    def test_staging_failure_writes_neither_file(self):
        real_stage = server.stage_json
        def fail_sources(path, data):
            if path.endswith('episode_sources.json'):
                raise OSError('Simulated staging failure')
            return real_stage(path, data)
        with mock.patch.object(server, 'stage_json', side_effect=fail_sources):
            self.assertEqual(self.save().status_code, 500)
        self.assertEqual(sorted(os.listdir(self.temp_dir.name)), ['items.json', 'sources.json'])
        self.assert_original_untouched()

    def test_overwrite_original_alias_existing_file_and_same_target_rejected(self):
        alias = self.path('alias.json')
        os.symlink(server.ITEMS_PATH, alias)
        existing = self.write_json('existing.json', [{'precious': True}])
        for targets in [dict(items_path=server.ITEMS_PATH), dict(sources_path=server.SOURCES_PATH),
                        dict(items_path=alias), dict(items_path=existing),
                        dict(items_path=self.path('same.json'), sources_path=self.path('same.json'))]:
            with self.subTest(targets=targets):
                self.assertEqual(self.save(**targets).status_code, 422)
                self.assert_original_untouched()
        self.assertEqual(server.load_json(existing), [{'precious': True}])

    def test_racing_destination_is_not_overwritten(self):
        real_link = os.link
        def race(source, destination):
            if destination.endswith('episode_sources.json'):
                self.write_json('episode_sources.json', [{'racing': True}])
            return real_link(source, destination)
        with mock.patch.object(server.os, 'link', side_effect=race):
            self.assertEqual(self.save().status_code, 500)
        self.assertFalse(os.path.exists(self.path('episode_items.json')))
        self.assertEqual(server.load_json(self.path('episode_sources.json')), [{'racing': True}])
        self.assert_original_untouched()

    def test_stale_items_or_sources_block_preview_save_and_open(self):
        for document in ('items', 'sources'):
            with self.subTest(document=document):
                preview = self.preview()
                sessions = self.sessions()
                saved = self.save(preview).json
                server.advance_document_revision(document)
                response = self.client.post('/api/preview_project', json=sessions)
                self.assertEqual(response.status_code, 409)
                # Use an unsaved preview to test the save path (saved requests are idempotent).
                fresh = self.preview()
                server.advance_document_revision(document)
                self.assertEqual(self.save(fresh, items_path=self.path('new.json')).status_code, 409)
                response = self.client.post('/api/open_project', json={**sessions, 'project_token': saved['project_token']})
                self.assertEqual(response.status_code, 409)
                for name in ('episode_items.json', 'episode_sources.json'):
                    os.unlink(self.path(name))

    def test_session_switch_during_native_dialog_is_rechecked(self):
        preview = self.preview()
        def choose(**kwargs):
            server.reset_document_state('sources')
            return self.path('target-' + ('items' if 'Items' in kwargs['title'] else 'sources') + '.json')
        with mock.patch.object(server, 'TK_AVAILABLE', True), mock.patch.object(server, 'tk', create=True), \
                mock.patch.object(server, 'filedialog', create=True) as dialogs:
            dialogs.asksaveasfilename.side_effect = choose
            response = self.client.post('/api/save_project', json={'preview_token': preview['preview_token']})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(sorted(os.listdir(self.temp_dir.name)), ['items.json', 'sources.json'])

    def test_external_file_edit_invalidates_snapshot(self):
        preview = self.preview()
        self.write_json('sources.json', self.sources + [{'id_source': 'external-edit'}])
        self.assertEqual(self.save(preview).status_code, 409)
        self.assertFalse(os.path.exists(self.path('episode_items.json')))

    def test_preview_errors_cannot_be_bypassed(self):
        for items, sources in [([{'id_item': 'a', 'id_source': 'missing'}], []),
                               ([{'id_item': 'a', 'nested_under': 'a'}], [])]:
            self.write_json('items.json', items)
            self.write_json('sources.json', sources)
            preview = self.preview(scope='checked', selected_ids=['a'])
            self.assertTrue(preview['errors'])
            self.assertEqual(self.save(preview).status_code, 422)

    def test_open_failure_never_partially_activates(self):
        saved = self.save().json
        with mock.patch.object(server, 'save_json', side_effect=OSError('Config unavailable')):
            response = self.client.post('/api/open_project', json={**self.sessions(), 'project_token': saved['project_token']})
        self.assertEqual(response.status_code, 500)
        self.assert_original_untouched()
        self.write_text('episode_sources.json', '{broken')
        response = self.client.post('/api/open_project', json={**self.sessions(), 'project_token': saved['project_token']})
        self.assertEqual(response.status_code, 422)
        self.assert_original_untouched()

    def test_expired_preview_gui_fallback_and_retry(self):
        preview = self.preview()
        with mock.patch.object(server, 'TK_AVAILABLE', False):
            response = self.client.post('/api/save_project', json={'preview_token': preview['preview_token']})
        self.assertEqual(response.json['status'], 'gui_unavailable')
        saved = self.save(preview)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.save(preview).json, saved.json)
        server.PROJECT_PREVIEWS[preview['preview_token']]['created'] -= server.PROJECT_PREVIEW_TTL + 1
        self.assertEqual(self.save(preview).status_code, 422)
        self.assert_original_untouched()


if __name__ == '__main__':
    unittest.main()
