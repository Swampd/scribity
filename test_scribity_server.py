import json
import inspect
import os
import tempfile
import unittest
from unittest import mock

import scribity_server as server


class ScribityServerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.original_state = {
            "ITEMS_PATH": server.ITEMS_PATH,
            "SOURCES_PATH": server.SOURCES_PATH,
            "CONFIG_PATH": server.CONFIG_PATH,
            "ITEMS_READY": getattr(server, "ITEMS_READY", None),
            "SOURCES_READY": getattr(server, "SOURCES_READY", None),
        }
        self.addCleanup(self.restore_server_state)

        server.CONFIG_PATH = self.path("scribity_config.json")
        server.ITEMS_PATH = self.write_json("items.json", [])
        server.SOURCES_PATH = self.write_json("sources.json", [])
        server.ITEMS_READY = False
        server.SOURCES_READY = False
        server.app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
        self.client = server.app.test_client()

    def restore_server_state(self):
        server.ITEMS_PATH = self.original_state["ITEMS_PATH"]
        server.SOURCES_PATH = self.original_state["SOURCES_PATH"]
        server.CONFIG_PATH = self.original_state["CONFIG_PATH"]
        for name in ("ITEMS_READY", "SOURCES_READY"):
            original = self.original_state[name]
            if original is None:
                try:
                    delattr(server, name)
                except AttributeError:
                    pass
            else:
                setattr(server, name, original)

    def path(self, filename):
        return os.path.join(self.temp_dir.name, filename)

    def write_json(self, filename, data):
        path = self.path(filename)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return path

    def write_text(self, filename, content):
        path = self.path(filename)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def load_document(self, path):
        """Call the current or desired loader signature while testing its behavior."""
        parameters = inspect.signature(server.load_json).parameters
        if "template" in parameters:
            return server.load_json(path, None)
        return server.load_json(path)


class StrictJsonLoadingTests(ScribityServerTestCase):
    def test_missing_file_raises_without_creating_it(self):
        missing_path = self.path("missing.json")

        with self.assertRaises(Exception) as caught:
            self.load_document(missing_path)

        self.assertEqual(getattr(caught.exception, "kind", None), "not_found")
        self.assertFalse(os.path.exists(missing_path))

    def test_malformed_json_raises_without_changing_the_file(self):
        malformed_path = self.write_text("malformed.json", '{"broken":')

        with self.assertRaises(Exception) as caught:
            self.load_document(malformed_path)

        self.assertEqual(getattr(caught.exception, "kind", None), "invalid_json")
        with open(malformed_path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), '{"broken":')

    def test_non_array_json_is_rejected(self):
        object_path = self.write_json("object.json", {"items": []})

        with self.assertRaises(Exception) as caught:
            self.load_document(object_path)

        self.assertEqual(getattr(caught.exception, "kind", None), "invalid_shape")

    def test_array_entries_must_be_objects(self):
        scalar_path = self.write_json("scalar.json", [{"id_item": "ok"}, 7])

        with self.assertRaises(Exception) as caught:
            self.load_document(scalar_path)

        self.assertEqual(getattr(caught.exception, "kind", None), "invalid_shape")


class JsonRouteSafetyTests(ScribityServerTestCase):
    def test_failed_manual_switch_keeps_active_path_and_config(self):
        original_path = server.ITEMS_PATH
        server.save_config()
        with open(server.CONFIG_PATH, "r", encoding="utf-8") as handle:
            original_config = handle.read()
        missing_path = self.path("typo-items.json")

        response = self.client.post("/api/switch_items", json={"path": missing_path})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(server.ITEMS_PATH, original_path)
        self.assertFalse(os.path.exists(missing_path))
        with open(server.CONFIG_PATH, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), original_config)

    def test_invalid_initial_document_returns_a_load_error(self):
        server.ITEMS_PATH = self.write_text("broken-items.json", "[")

        response = self.client.get("/api/data")

        self.assertEqual(response.status_code, 422)
        payload = response.get_json()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["document"], "items")
        self.assertEqual(payload["kind"], "invalid_json")
        self.assertNotIn("items", payload)

    def test_failed_initial_load_blocks_item_saves(self):
        original_content = "["
        server.ITEMS_PATH = self.write_text("broken-items.json", original_content)
        server.ITEMS_READY = True

        self.client.get("/api/data")
        response = self.client.post("/api/save_items", json=[])

        self.assertEqual(response.status_code, 409)
        with open(server.ITEMS_PATH, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), original_content)

    def test_successful_initial_load_enables_saves(self):
        response = self.client.get("/api/data")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(server.ITEMS_READY)
        self.assertTrue(server.SOURCES_READY)
        save_response = self.client.post(
            "/api/save_items",
            json=[{"id_item": "saved"}],
        )
        self.assertEqual(save_response.status_code, 200)


class ParserAppendSaveTests(ScribityServerTestCase):
    def setUp(self):
        super().setUp()
        self.original_items = [{"id_item": "existing"}]
        self.original_sources = [{"id_source": "existing-source"}]
        server.ITEMS_PATH = self.write_json("items.json", self.original_items)
        server.SOURCES_PATH = self.write_json("sources.json", self.original_sources)
        server.ITEMS_READY = True
        server.SOURCES_READY = True

    def read_json(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_append_import_saves_both_completed_snapshots(self):
        new_items = self.original_items + [{"id_item": "imported"}]
        new_sources = self.original_sources + [{"id_source": "imported-source"}]

        response = self.client.post(
            "/api/append_import",
            json={"items": new_items, "sources": new_sources},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        self.assertEqual(self.read_json(server.ITEMS_PATH), new_items)
        self.assertEqual(self.read_json(server.SOURCES_PATH), new_sources)

    def test_append_import_restores_items_when_sources_commit_fails(self):
        new_items = self.original_items + [{"id_item": "imported"}]
        new_sources = self.original_sources + [{"id_source": "imported-source"}]
        real_replace = os.replace
        source_commit_failed = False

        def fail_first_source_commit(source, destination):
            nonlocal source_commit_failed
            if destination == server.SOURCES_PATH and not source_commit_failed:
                source_commit_failed = True
                raise OSError("simulated sources write failure")
            return real_replace(source, destination)

        with mock.patch.object(server.os, "replace", side_effect=fail_first_source_commit):
            response = self.client.post(
                "/api/append_import",
                json={"items": new_items, "sources": new_sources},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["status"], "error")
        self.assertEqual(self.read_json(server.ITEMS_PATH), self.original_items)
        self.assertEqual(self.read_json(server.SOURCES_PATH), self.original_sources)

    def test_append_import_retains_backup_when_rollback_also_fails(self):
        new_items = self.original_items + [{"id_item": "imported"}]
        new_sources = self.original_sources + [{"id_source": "imported-source"}]
        real_replace = os.replace
        item_commit_count = 0

        def fail_source_commit_and_items_rollback(source, destination):
            nonlocal item_commit_count
            if destination == server.SOURCES_PATH:
                raise OSError("simulated sources write failure")
            if destination == server.ITEMS_PATH:
                item_commit_count += 1
                if item_commit_count == 2:
                    raise OSError("simulated rollback failure")
            return real_replace(source, destination)

        with mock.patch.object(
            server.os,
            "replace",
            side_effect=fail_source_commit_and_items_rollback,
        ):
            response = self.client.post(
                "/api/append_import",
                json={"items": new_items, "sources": new_sources},
            )

        self.assertEqual(response.status_code, 500)
        message = response.get_json()["message"]
        backup_path = message.split(" remains at ", 1)[1].rsplit(": ", 1)[0]
        self.assertTrue(os.path.exists(backup_path))
        os.unlink(backup_path)


if __name__ == "__main__":
    unittest.main()
