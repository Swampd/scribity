import json
from pathlib import Path
import tempfile
import unittest

from parse_drr import parse_mdx_file, parse_mdx_folder

FIXTURES = Path(__file__).parent / 'tests/fixtures/drr'
GOOD = (FIXTURES / 'metadata-history.mdx').read_text()


class ReportCompatibilityTests(unittest.TestCase):
    def parse(self, content=GOOD, name='example.mdx'):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_text(content)
            return parse_mdx_file(str(path))

    def test_metadata_history_sample_matches_expected_output(self):
        result = self.parse()
        expected = json.loads((FIXTURES / 'metadata-history.expected.json').read_text())
        self.assertEqual([i['event_date_yyyy-mm-dd'] for i in result['items']], expected['event_dates'])
        self.assertEqual(result['report']['report_id'], expected['report_id'])
        self.assertEqual(result['report']['schema_version'], expected['schema_version'])
        for key in ('publishedOn', 'updatedOn'):
            self.assertEqual(result['report']['metadata'][key], expected[key])
        self.assertEqual([i['quote_original'] for i in result['items']], expected['quotes'])
        self.assertEqual([i['report_provenance']['citation_number'] for i in result['items']], expected['citation_numbers'])
        self.assertEqual(len(result['sources']), expected['source_count'])
        self.assertEqual([d['code'] for d in result['diagnostics']], expected['diagnostic_codes'])
        self.assertTrue(result['can_import'])
        for record in result['items'] + result['sources']:
            meta = record['report_provenance']['metadata']
            self.assertEqual(meta['author'], {'name': 'Example Author'})
            self.assertEqual(meta['custom'], {'reviewed': False, 'labels': ['sample', 'compatibility']})
            self.assertEqual(meta['historicalScope'], [1901, 1976])
        self.assertNotEqual(result['sources'][0]['id_source'], result['sources'][1]['id_source'])
        self.assertEqual(result['items'][1]['related_facts'], result['items'][2]['related_facts'])

    def test_rename_preserves_stable_item_source_and_group_identities(self):
        first, second = self.parse(name='first.mdx'), self.parse(name='renamed.mdx')
        self.assertEqual([i['id_item'] for i in first['items']], [i['id_item'] for i in second['items']])
        self.assertEqual([s['id_source'] for s in first['sources']], [s['id_source'] for s in second['sources']])
        self.assertEqual(first['items'][1]['related_facts'], second['items'][1]['related_facts'])

    def test_draft_date_null_and_unknown_metadata_survive(self):
        result = self.parse(GOOD.replace("publishedOn: '2026-10-16'", 'publishedOn: null'))
        self.assertTrue(result.get('can_import'))
        self.assertIsNone(result['report']['metadata']['publishedOn'])
        self.assertEqual(result['report_date'], '')

    def test_unversioned_reports_remain_readable_with_migration_warning(self):
        result = self.parse(GOOD.replace('drrSchemaVersion: 1\nreportId: sample-history-report\n', ''))
        self.assertTrue(result.get('can_import'))
        self.assertIn('legacy_report', [d['code'] for d in result['diagnostics']])

    def test_unsafe_invalid_or_unsupported_metadata_blocks_import(self):
        variants = [
            ('unsupported_version', GOOD.replace('drrSchemaVersion: 1', 'drrSchemaVersion: 99')),
            ('unsupported_version', GOOD.replace('drrSchemaVersion: 1', 'drrSchemaVersion: null')),
            ('missing_report_id', GOOD.replace('reportId: sample-history-report\n', '')),
            ('invalid_publication_date', GOOD.replace("'2026-10-16'", "'1901'")),
            ('invalid_frontmatter', GOOD.replace('author:', 'author: !!python/object/apply:os.system')),
            ('invalid_frontmatter', GOOD.replace('summary:', 'title: Duplicate\nsummary:')),
            ('invalid_frontmatter', GOOD.replace('custom:', 'alias: &a [*a]\ncustom:')),
            ('invalid_frontmatter', GOOD.replace('---\n#', '#', 1)),
        ]
        for code, content in variants:
            with self.subTest(code=code, content=content[:80]):
                result = self.parse(content)
                self.assertFalse(result.get('can_import', True))
                self.assertIn(code, [d['code'] for d in result['diagnostics']])

    def test_missing_duplicate_and_malformed_sources_are_actionable(self):
        for code, content in [
            ('missing_source', GOOD.replace('1901. [1]', '1901. [99]')),
            ('duplicate_source', GOOD.replace('2. Example alternate', '1. Example alternate')),
            ('malformed_source', GOOD.replace('<https://example.com/evidence>', 'https://example.com/evidence', 1)),
        ]:
            with self.subTest(code=code):
                result = self.parse(content)
                self.assertFalse(result.get('can_import', True))
                diagnostic = next(d for d in result['diagnostics'] if d['code'] == code)
                self.assertGreater(diagnostic['line'], 0)
                self.assertTrue(diagnostic['excerpt'])

    def test_uncited_trailing_and_nonstandard_citations_are_not_silently_lost(self):
        for body, code in [
            ('Uncited substantive evidence.', 'uncited_text'),
            ('Cited. [1] Trailing substantive evidence.', 'trailing_text'),
            ('Evidence. [1–2]', 'unsupported_citation'),
            ('Evidence. [cite: 1]', 'unsupported_citation'),
            ('Evidence. [1][2]', 'unsupported_citation'),
            ('Evidence. [^1]', 'unsupported_citation'),
        ]:
            with self.subTest(body=body):
                result = self.parse(GOOD.replace('A sample event occurred in 1901. [1]', body))
                self.assertFalse(result.get('can_import', True))
                diagnostic = next(d for d in result['diagnostics'] if d['code'] == code)
                self.assertIn(body, diagnostic['excerpt'])

    def test_intro_is_extracted_and_flagged_instead_of_dropped(self):
        result = self.parse(GOOD.replace('## Findings', 'Opening evidence. [2]\n\n## Findings'))
        self.assertIn('Opening evidence.', [i['quote_original'] for i in result['items']])
        self.assertIn('opening_content', [d['code'] for d in result['diagnostics']])

    def test_components_fences_and_expressions_are_flagged_with_original_content(self):
        for body in ['<SignalChart data={[{value: 99}]} />', '<ReportCallout>Unique evidence. [1]</ReportCallout>',
                     '```js\nsecretEvidence()\n```', '{hiddenEvidence}', 'export const evidence = 99;']:
            with self.subTest(body=body):
                result = self.parse(GOOD.replace('A sample event occurred in 1901. [1]', body))
                self.assertFalse(result.get('can_import', True))
                self.assertTrue(any(body in d['excerpt'] for d in result['diagnostics']))

    def test_mixed_table_does_not_assign_cited_row_sources_to_uncited_row(self):
        table = '| Fact |\n| --- |\n| Supported. [1] |\n| Uncited row. |'
        result = self.parse(GOOD.replace('A sample event occurred in 1901. [1]', table))
        self.assertFalse(result.get('can_import', True))
        self.assertFalse(any('Uncited row' in i['quote_original'] and i['id_source'] for i in result['items']))
        self.assertTrue(any('Uncited row' in d['excerpt'] for d in result['diagnostics']))

    def test_folder_preserves_metadata_and_rejects_duplicate_report_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ['one.mdx', 'two.mdx']:
                (Path(folder) / name).write_text(GOOD)
            result = parse_mdx_folder(folder)
        self.assertFalse(result.get('can_import', True))
        self.assertIn('duplicate_report_id', [d['code'] for d in result['diagnostics']])
        self.assertEqual(result['files'][0]['report']['metadata']['author'], {'name': 'Example Author'})

    def test_double_quoted_publication_date_is_not_an_event_date(self):
        result = self.parse(GOOD.replace("'2026-10-16'", '"2026-10-16"'))
        self.assertEqual(result['report_date'], '2026-10-16')
        self.assertEqual([i['event_date_yyyy-mm-dd'] for i in result['items']], ['', '', ''])

    def test_plain_url_autolinks_lists_and_cited_tables_remain_extractable(self):
        for body, count in [
            ('See <https://example.com/evidence> for the event. [1]', 3),
            ('- First evidence. [1]\n- Second evidence. [2]', 4),
            ('> First evidence. [1]', 3),
            ('| Fact |\n| --- |\n| First evidence. [1] |\n| Second evidence. [2] |', 4),
        ]:
            with self.subTest(body=body):
                result = self.parse(GOOD.replace('A sample event occurred in 1901. [1]', body))
                self.assertTrue(result['can_import'], result['diagnostics'])
                self.assertEqual(len(result['items']), count)

    def test_bibliography_links_with_invalid_brackets_are_diagnosed(self):
        result = self.parse(GOOD.replace('https://example.com/evidence', 'https://[invalid'))
        self.assertFalse(result['can_import'])
        self.assertIn('malformed_source', [d['code'] for d in result['diagnostics']])

    def test_multiple_top_level_titles_and_cited_table_headers_need_review(self):
        for body, code in [
            ('# Another title\n\nEvidence. [1]', 'unsupported_heading'),
            ('| Header evidence. [2] |\n| --- |\n| Row evidence. [1] |', 'unsupported_table'),
        ]:
            result = self.parse(GOOD.replace('A sample event occurred in 1901. [1]', body))
            self.assertFalse(result['can_import'])
            self.assertIn(code, [d['code'] for d in result['diagnostics']])
