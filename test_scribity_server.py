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


class SavePayloadValidationTests(ScribityServerTestCase):
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

    def post_json_value(self, route, value):
        return self.client.post(
            route,
            data=json.dumps(value),
            content_type="application/json",
        )

    def assert_invalid_shape(self, response, document):
        self.assertEqual(response.status_code, 422)
        payload = response.get_json()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["kind"], "invalid_shape")
        self.assertEqual(payload["document"], document)

    def test_direct_save_endpoints_reject_invalid_shapes_without_writing(self):
        cases = (
            ("/api/save_items", "items", "ITEMS_PATH", self.original_items),
            ("/api/save_sources", "sources", "SOURCES_PATH", self.original_sources),
        )
        invalid_values = (None, {"unexpected": "object"}, ["scalar"])

        for route, document, path_name, original_data in cases:
            for invalid_value in invalid_values:
                with self.subTest(route=route, invalid_value=invalid_value):
                    response = self.post_json_value(route, invalid_value)

                    self.assert_invalid_shape(response, document)
                    self.assertEqual(self.read_json(getattr(server, path_name)), original_data)

    def test_save_as_endpoints_validate_before_opening_a_dialog(self):
        cases = (
            ("/api/save_items_as", "items", "ITEMS_PATH"),
            ("/api/save_sources_as", "sources", "SOURCES_PATH"),
        )

        for route, document, path_name in cases:
            original_path = getattr(server, path_name)
            with self.subTest(route=route), \
                    mock.patch.object(server, "TK_AVAILABLE", True), \
                    mock.patch.object(server, "tk", create=True) as tk_module, \
                    mock.patch.object(server, "filedialog", create=True) as file_dialog:
                response = self.client.post(route, json={"data": [17]})

                self.assert_invalid_shape(response, document)
                tk_module.Tk.assert_not_called()
                file_dialog.asksaveasfilename.assert_not_called()
                self.assertEqual(getattr(server, path_name), original_path)

    def test_save_new_document_validates_both_documents_before_dialogs_or_writes(self):
        cases = (
            ({"items": None, "sources": self.original_sources}, "items"),
            ({"items": self.original_items, "sources": [False]}, "sources"),
        )

        for payload, document in cases:
            with self.subTest(document=document), \
                    mock.patch.object(server, "TK_AVAILABLE", True), \
                    mock.patch.object(server, "tk", create=True) as tk_module, \
                    mock.patch.object(server, "filedialog", create=True) as file_dialog:
                response = self.client.post("/api/save_new_document", json=payload)

                self.assert_invalid_shape(response, document)
                tk_module.Tk.assert_not_called()
                file_dialog.asksaveasfilename.assert_not_called()
                self.assertEqual(server.ITEMS_PATH, self.path("items.json"))
                self.assertEqual(server.SOURCES_PATH, self.path("sources.json"))
                self.assertEqual(self.read_json(server.ITEMS_PATH), self.original_items)
                self.assertEqual(self.read_json(server.SOURCES_PATH), self.original_sources)


class TwoFileCreationSafetyTests(ScribityServerTestCase):
    def setUp(self):
        super().setUp()
        server.ITEMS_READY = True
        server.SOURCES_READY = True
        self.active_items_path = server.ITEMS_PATH
        self.active_sources_path = server.SOURCES_PATH

    def post_with_dialog_paths(self, route, payload, items_path, sources_path):
        with mock.patch.object(server, "TK_AVAILABLE", True), \
                mock.patch.object(server, "tk", create=True), \
                mock.patch.object(server, "filedialog", create=True) as file_dialog:
            file_dialog.asksaveasfilename.side_effect = [items_path, sources_path]
            return self.client.post(route, json=payload)

    def assert_active_paths_unchanged(self):
        self.assertEqual(server.ITEMS_PATH, self.active_items_path)
        self.assertEqual(server.SOURCES_PATH, self.active_sources_path)

    def test_creation_routes_reject_the_same_canonical_path_without_writing(self):
        cases = (
            ("/api/new_document", {}, "new-document-same.json"),
            (
                "/api/save_new_document",
                {"items": [{"id_item": "new"}], "sources": [{"id_source": "new"}]},
                "save-new-same.json",
            ),
        )

        for route, payload, filename in cases:
            target = self.path(filename)
            equivalent_target = os.path.join(self.temp_dir.name, ".", filename)
            with self.subTest(route=route):
                response = self.post_with_dialog_paths(
                    route,
                    payload,
                    target,
                    equivalent_target,
                )

                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.get_json()["kind"], "path_conflict")
                self.assertFalse(os.path.exists(target))
                self.assert_active_paths_unchanged()

    def test_creation_routes_commit_both_documents_before_updating_active_paths(self):
        cases = (
            ("/api/new_document", {}, [], []),
            (
                "/api/save_new_document",
                {"items": [{"id_item": "new"}], "sources": [{"id_source": "new"}]},
                [{"id_item": "new"}],
                [{"id_source": "new"}],
            ),
        )

        for index, (route, payload, expected_items, expected_sources) in enumerate(cases):
            items_target = self.path(f"successful-items-{index}.json")
            sources_target = self.path(f"successful-sources-{index}.json")
            with self.subTest(route=route):
                response = self.post_with_dialog_paths(
                    route,
                    payload,
                    items_target,
                    sources_target,
                )

                self.assertEqual(response.status_code, 200)
                with open(items_target, "r", encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle), expected_items)
                with open(sources_target, "r", encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle), expected_sources)
                self.assertEqual(server.ITEMS_PATH, items_target)
                self.assertEqual(server.SOURCES_PATH, sources_target)

            server.ITEMS_PATH = self.active_items_path
            server.SOURCES_PATH = self.active_sources_path

    def test_new_document_removes_first_new_file_when_second_commit_fails(self):
        items_target = self.path("new-items.json")
        sources_target = self.path("new-sources.json")
        real_replace = os.replace
        source_commit_failed = False

        def fail_first_source_commit(source, destination):
            nonlocal source_commit_failed
            if destination == sources_target and not source_commit_failed:
                source_commit_failed = True
                raise OSError("simulated sources write failure")
            return real_replace(source, destination)

        with mock.patch.object(server.os, "replace", side_effect=fail_first_source_commit):
            response = self.post_with_dialog_paths(
                "/api/new_document",
                {},
                items_target,
                sources_target,
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(os.path.exists(items_target))
        self.assertFalse(os.path.exists(sources_target))
        self.assert_active_paths_unchanged()

    def test_save_new_document_restores_existing_first_file_on_second_commit_failure(self):
        original_items = '[ { "id_item": "original formatting" } ]\n'
        original_sources = '[ { "id_source": "original source" } ]\n'
        items_target = self.write_text("destination-items.json", original_items)
        sources_target = self.write_text("destination-sources.json", original_sources)
        real_replace = os.replace
        source_commit_failed = False

        def fail_first_source_commit(source, destination):
            nonlocal source_commit_failed
            if destination == sources_target and not source_commit_failed:
                source_commit_failed = True
                raise OSError("simulated sources write failure")
            return real_replace(source, destination)

        with mock.patch.object(server.os, "replace", side_effect=fail_first_source_commit):
            response = self.post_with_dialog_paths(
                "/api/save_new_document",
                {
                    "items": [{"id_item": "replacement"}],
                    "sources": [{"id_source": "replacement"}],
                },
                items_target,
                sources_target,
            )

        self.assertEqual(response.status_code, 500)
        with open(items_target, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), original_items)
        with open(sources_target, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), original_sources)
        self.assert_active_paths_unchanged()

    def test_both_documents_are_staged_before_either_destination_changes(self):
        original_items = '[{"id_item": "untouched"}]\n'
        original_sources = '[{"id_source": "untouched"}]\n'
        items_target = self.write_text("staged-items.json", original_items)
        sources_target = self.write_text("staged-sources.json", original_sources)
        real_stage_json = server.stage_json

        def fail_sources_staging(path, data):
            if path == sources_target:
                raise OSError("simulated sources staging failure")
            return real_stage_json(path, data)

        with mock.patch.object(server, "stage_json", side_effect=fail_sources_staging):
            response = self.post_with_dialog_paths(
                "/api/save_new_document",
                {
                    "items": [{"id_item": "replacement"}],
                    "sources": [{"id_source": "replacement"}],
                },
                items_target,
                sources_target,
            )

        self.assertEqual(response.status_code, 500)
        with open(items_target, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), original_items)
        with open(sources_target, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), original_sources)
        self.assert_active_paths_unchanged()


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


class ServerStartupConfigurationTests(unittest.TestCase):
    def test_normal_launch_disables_debugger_and_reloader(self):
        options_builder = getattr(server, "server_run_options", None)

        self.assertIsNotNone(options_builder)
        self.assertEqual(
            options_builder({}),
            {"port": server.PORT, "debug": False, "use_reloader": False},
        )

    def test_debug_environment_flag_enables_development_mode(self):
        options_builder = getattr(server, "server_run_options", None)

        self.assertIsNotNone(options_builder)
        for flag in ("1", "true", "yes", "on", " TRUE "):
            with self.subTest(flag=flag):
                self.assertEqual(
                    options_builder({"SCRIBITY_DEBUG": flag}),
                    {"port": server.PORT, "debug": True, "use_reloader": True},
                )

    def test_unrecognized_debug_value_stays_disabled(self):
        options_builder = getattr(server, "server_run_options", None)

        self.assertIsNotNone(options_builder)
        self.assertEqual(
            options_builder({"SCRIBITY_DEBUG": "sometimes"}),
            {"port": server.PORT, "debug": False, "use_reloader": False},
        )


if __name__ == "__main__":
    unittest.main()
