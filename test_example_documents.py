import json
from pathlib import Path
import unittest


EXAMPLE_PAIRS = (
    ("research-items.json", "research-sources.json"),
    ("improv-items.json", "improv-sources.json"),
)


class ExampleDocumentTests(unittest.TestCase):
    def setUp(self):
        self.examples_dir = Path(__file__).parent / "examples"

    def load_document(self, filename):
        with (self.examples_dir / filename).open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_example_documents_are_small_arrays_of_objects(self):
        for items_filename, sources_filename in EXAMPLE_PAIRS:
            with self.subTest(document=items_filename):
                items = self.load_document(items_filename)
                self.assertIsInstance(items, list)
                self.assertTrue(items)
                self.assertLessEqual(len(items), 12)
                self.assertTrue(all(isinstance(item, dict) for item in items))

            with self.subTest(document=sources_filename):
                sources = self.load_document(sources_filename)
                self.assertIsInstance(sources, list)
                self.assertTrue(sources)
                self.assertLessEqual(len(sources), 12)
                self.assertTrue(all(isinstance(source, dict) for source in sources))

    def test_example_item_links_resolve_within_each_source_document(self):
        for items_filename, sources_filename in EXAMPLE_PAIRS:
            items = self.load_document(items_filename)
            sources = self.load_document(sources_filename)
            source_ids = [source.get("id_source") for source in sources]
            item_ids = [item.get("id_item") for item in items]

            with self.subTest(pair=items_filename):
                self.assertNotIn(None, source_ids)
                self.assertNotIn("", source_ids)
                self.assertEqual(len(source_ids), len(set(source_ids)))
                self.assertNotIn(None, item_ids)
                self.assertNotIn("", item_ids)
                self.assertEqual(len(item_ids), len(set(item_ids)))
                self.assertTrue(
                    all(item.get("id_source") in source_ids for item in items),
                    "Every example item must link to a source shipped in the same pair.",
                )


if __name__ == "__main__":
    unittest.main()
