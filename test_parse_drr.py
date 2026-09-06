import inspect
import os
import tempfile
import unittest
from unittest import mock

import parse_drr


REPORT_TEMPLATE = """---
publishedOn: "2026-01-01"
---
# {title}

## Findings

{fact} [1]

## Sources

1. {source_title} <{url}>
"""


class ParserSourceIdTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def write_report(self, filename, *, title, fact, source_title, url):
        path = os.path.join(self.temp_dir.name, filename)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(REPORT_TEMPLATE.format(
                title=title,
                fact=fact,
                source_title=source_title,
                url=url,
            ))
        return path

    def test_sanitized_filename_collisions_get_distinct_source_ids(self):
        first_path = self.write_report(
            "report-a.mdx",
            title="Report A",
            fact="First fact",
            source_title="First Source",
            url="https://example.com/first",
        )
        second_path = self.write_report(
            "report_a.mdx",
            title="Report B",
            fact="Second fact",
            source_title="Second Source",
            url="https://example.com/second",
        )

        result = parse_drr.parse_mdx_folder(self.temp_dir.name)

        self.assertEqual(len(result["sources"]), 2)
        source_ids = [source["id_source"] for source in result["sources"]]
        self.assertEqual(len(set(source_ids)), 2)
        item_source_ids = {item["id_source"] for item in result["items"]}
        self.assertEqual(item_source_ids, set(source_ids))
        self.assertEqual(result.get("collisions"), [])
        self.assertEqual(result["stats"].get("source_id_collisions"), 0)

        # Sanity-check the fixtures would collide under the legacy slug scheme.
        legacy_slugs = {
            parse_drr.re.sub(r"[^a-zA-Z0-9]", "_", os.path.splitext(os.path.basename(path))[0])[:50]
            for path in (first_path, second_path)
        }
        self.assertEqual(len(legacy_slugs), 1)

    def test_source_ids_are_stable_for_the_same_relative_path(self):
        self.assertIn(
            "report_identity",
            inspect.signature(parse_drr.parse_mdx_file).parameters,
        )
        first_root = tempfile.TemporaryDirectory()
        second_root = tempfile.TemporaryDirectory()
        self.addCleanup(first_root.cleanup)
        self.addCleanup(second_root.cleanup)
        relative_path = os.path.join("reports", "stable-report.mdx")

        first_path = os.path.join(first_root.name, relative_path)
        second_path = os.path.join(second_root.name, relative_path)
        os.makedirs(os.path.dirname(first_path))
        os.makedirs(os.path.dirname(second_path))
        content = REPORT_TEMPLATE.format(
            title="Stable Report",
            fact="Stable fact",
            source_title="Stable Source",
            url="https://example.com/stable",
        )
        for path in (first_path, second_path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)

        first = parse_drr.parse_mdx_file(first_path, report_identity=relative_path)
        second = parse_drr.parse_mdx_file(
            second_path,
            report_identity=relative_path.replace(os.sep, "\\"),
        )

        self.assertEqual(first["sources"][0]["id_source"], second["sources"][0]["id_source"])

    def test_folder_parse_explicitly_reports_generated_id_collisions(self):
        self.write_report(
            "report-a.mdx",
            title="Report A",
            fact="First fact",
            source_title="First Source",
            url="https://example.com/first",
        )
        self.write_report(
            "report_a.mdx",
            title="Report B",
            fact="Second fact",
            source_title="Second Source",
            url="https://example.com/second",
        )

        with mock.patch.object(
            parse_drr,
            "_report_identity_digest",
            return_value="forcedcollision",
            create=True,
        ):
            result = parse_drr.parse_mdx_folder(self.temp_dir.name)

        self.assertIsNotNone(result.get("collisions"))
        self.assertEqual(len(result.get("collisions", [])), 1)
        collision = result["collisions"][0]
        self.assertEqual(collision["kind"], "source_id_collision")
        self.assertEqual(set(collision["reports"]), {"report-a.mdx", "report_a.mdx"})
        self.assertEqual(result["stats"]["source_id_collisions"], 1)


if __name__ == "__main__":
    unittest.main()
