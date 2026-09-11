"""
Scribity Server — py scribity_server.py

"""

import json
import os
import shutil
import sys
import tempfile
import threading
import uuid
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

# --- ATTEMPT TO LOAD GUI LIB ---
TK_AVAILABLE = False
try:
    import tkinter as tk
    from tkinter import filedialog
    TK_AVAILABLE = True
except ImportError:
    pass
except Exception:
    pass

# --- CONFIGURATION ---
PORT      = 8000
HTML_FILE = 'dashboard.html'

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(BASE_DIR, HTML_FILE)
CONFIG_PATH = os.path.join(BASE_DIR, 'scribity_config.json')


def server_run_options(environ=None):
    """Return Flask launch options, with development mode explicitly opt-in."""
    environment = os.environ if environ is None else environ
    debug_value = str(environment.get('SCRIBITY_DEBUG', '')).strip().lower()
    debug_enabled = debug_value in {'1', 'true', 'yes', 'on'}
    return {
        'port': PORT,
        'debug': debug_enabled,
        'use_reloader': debug_enabled,
    }

# Default file paths — relative to the server script.
# Use the file picker (Items/Sources buttons) to load a different file.
DEFAULT_ITEMS_PATH   = os.path.join(BASE_DIR, 'items.json')
DEFAULT_SOURCES_PATH = os.path.join(BASE_DIR, 'sources.json')
ITEMS_PATH   = DEFAULT_ITEMS_PATH
SOURCES_PATH = DEFAULT_SOURCES_PATH

app = Flask(__name__)
CORS(app)

# Saves are allowed only after the corresponding document has loaded successfully
# or has been created explicitly through a save/new-document action.
ITEMS_READY = False
SOURCES_READY = False
SAVE_LOCK = threading.RLock()
ITEMS_DOCUMENT = {"token": uuid.uuid4().hex, "revision": 0}
SOURCES_DOCUMENT = {"token": uuid.uuid4().hex, "revision": 0}

# --- TEMPLATES BASED ON NEW SCHEMA ---

ITEM_TEMPLATE = {
  "id_item": "",
  "id_source": "",
  "id_script": 0,
  "id_subpart": [],
  "rule_name": [],
  "rule_number": [],
  "subpart_name": [],
  "subpart_number": [],
  "quote_original": "",
  "quote_translation": "",
  "quoted_speaker_name": "",
  "language": "",
  "contains_example": False,
  "contains_only_example": False,
  "example": "",
  "example_02": "",
  "example_03": "",
  "example_note": "",
  "example_02_note": "",
  "example_03_note": "",
  "short_cite": "",
  "url": "",
  "script_part": "",
  "edit_tags": "",
  "relevance_tags": [],
  "needs_verification": False,
  "script_notes": "",
  "script_tags": "",
  "audio_tags": "",
  "id_extra_01": "",
  "id_extra_02": "",
  "event_date_yyyy-mm-dd": "",
  "event_time": "",
  "latitude": "",
  "longitude": "",
  "location_name": "",
  "user_01_comments": "",
  "user_02_comments": ""
}

SOURCE_TEMPLATE = {
  "id_source": "",
  "short_cite": "",
  "author": "",
  "title": "",
  "publication": "",
  "additional_source_details": "",
  "date_published": "",
  "date_accessed": "",
  "url": "",
  "archive_url": "",
  "page": "",
  "timestamp": "",
  "source_within_source_short_cite": "",
  "source_within_source_full_link": "",
  "related_reading": "",
  "needs_verification": False,
  "relevance_tags": [],
  "script_tags": "",
  "script_notes": "",
  "edit_tags": "",
  "user_01_comments": "",
  "user_02_comments": "",
  "to_do": ""
}

def normalize_bool(val):
    """Normalize inconsistent boolean values (YES/no/1/0/true/false) to Python bool."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in ('yes', 'y', '1', 'true')
    return False

def normalize_items(data):
    """Normalize boolean fields and auto-detect contains_example on item data."""
    for item in data:
        # Normalize boolean flags
        item['contains_example'] = normalize_bool(item.get('contains_example', False))
        item['contains_only_example'] = normalize_bool(item.get('contains_only_example', False))
        # Auto-set contains_example if any example text exists
        has_text = any(item.get(f, '') for f in ('example', 'example_02', 'example_03'))
        if has_text:
            item['contains_example'] = True
    return data

class JsonDocumentError(Exception):
    """A document could not be safely loaded as a Scribity JSON array."""

    def __init__(self, kind, path, message, status_code):
        super().__init__(message)
        self.kind = kind
        self.path = path
        self.status_code = status_code


class JsonDocumentShapeError(ValueError):
    """A value is not a Scribity document represented as an array of objects."""


def validate_document_structure(data, label="Document"):
    """Return data when it is a JSON-style array of objects, otherwise raise."""
    if not isinstance(data, list):
        raise JsonDocumentShapeError(f"{label} must be a JSON array.")
    if any(not isinstance(entry, dict) for entry in data):
        raise JsonDocumentShapeError(
            f"Every entry in {label.lower()} must be a JSON object."
        )
    return data


def load_json(path):
    """Load an existing Scribity JSON document without creating or repairing it."""
    if not os.path.exists(path):
        raise JsonDocumentError(
            "not_found",
            path,
            f"File not found: {path}",
            404,
        )

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as error:
        raise JsonDocumentError(
            "invalid_json",
            path,
            f"Invalid JSON in {os.path.basename(path)}: {error}",
            422,
        ) from error
    except OSError as error:
        raise JsonDocumentError(
            "io_error",
            path,
            f"Could not read {path}: {error}",
            500,
        ) from error

    try:
        validate_document_structure(data, os.path.basename(path))
    except JsonDocumentShapeError as error:
        raise JsonDocumentError(
            "invalid_shape",
            path,
            str(error),
            422,
        ) from error

    return data


def json_document_error_response(error, document):
    """Return a consistent, user-readable API response for a load failure."""
    return jsonify({
        "status": "error",
        "kind": error.kind,
        "document": document,
        "filename": os.path.basename(error.path),
        "path": error.path,
        "message": str(error),
        # Keep recovery actions (New Document / Save New Document) usable even
        # when the configured file cannot be loaded.
        "items_document": current_document_state("items"),
        "sources_document": current_document_state("sources"),
    }), error.status_code


def invalid_document_shape_response(error, document):
    """Return a consistent response when a save payload is structurally unsafe."""
    return jsonify({
        "status": "error",
        "kind": "invalid_shape",
        "document": document,
        "message": str(error),
    }), 422


def current_document_state(document):
    """Return a copy of the active document's opaque identity and revision."""
    state = ITEMS_DOCUMENT if document == "items" else SOURCES_DOCUMENT
    return {"token": state["token"], "revision": state["revision"]}


def reset_document_state(document):
    """Invalidate requests created for the previously active file."""
    state = ITEMS_DOCUMENT if document == "items" else SOURCES_DOCUMENT
    state["token"] = uuid.uuid4().hex
    state["revision"] = 0
    return current_document_state(document)


def advance_document_revision(document):
    state = ITEMS_DOCUMENT if document == "items" else SOURCES_DOCUMENT
    state["revision"] += 1
    return current_document_state(document)


def document_request_is_current(document, supplied):
    """Check an optimistic-lock value while the caller holds SAVE_LOCK."""
    if not isinstance(supplied, dict):
        return False
    expected = ITEMS_DOCUMENT if document == "items" else SOURCES_DOCUMENT
    revision = supplied.get("revision")
    return (
        supplied.get("token") == expected["token"]
        and isinstance(revision, int)
        and not isinstance(revision, bool)
        and revision == expected["revision"]
    )


def stale_document_response(document):
    return jsonify({
        "status": "error",
        "kind": "stale_document",
        "document": document,
        "message": (
            f"{document.capitalize()} were not saved because another file or "
            "newer revision is active. Reload before editing again."
        ),
    }), 409


def find_source_id_collisions(existing_sources, imported_sources):
    """Return IDs duplicated within an import or conflicting with stored sources."""
    existing_by_id = {
        source.get('id_source'): source
        for source in existing_sources
        if source.get('id_source')
    }
    imported_by_id = {}
    collision_ids = set()

    for source in imported_sources:
        source_id = source.get('id_source')
        if not source_id:
            continue
        if source_id in imported_by_id:
            collision_ids.add(source_id)
        else:
            imported_by_id[source_id] = source

        existing_source = existing_by_id.get(source_id)
        if existing_source is not None and existing_source != source:
            collision_ids.add(source_id)

    return sorted(collision_ids)


def save_json(path, data):
    """Generic JSON saver with atomic write to prevent corruption."""
    with SAVE_LOCK:
        tmp_path = path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        # Atomic rename (overwrites existing file)
        os.replace(tmp_path, path)


def stage_json(path, data):
    """Write JSON to a unique temporary file beside its destination."""
    directory = os.path.dirname(os.path.abspath(path))
    prefix = f".{os.path.basename(path)}."
    fd, tmp_path = tempfile.mkstemp(prefix=prefix, suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path


def paths_refer_to_same_file(first_path, second_path):
    """Return whether two selected paths resolve to the same destination."""
    first_canonical = os.path.normcase(os.path.realpath(os.path.abspath(first_path)))
    second_canonical = os.path.normcase(os.path.realpath(os.path.abspath(second_path)))
    if first_canonical == second_canonical:
        return True
    try:
        return os.path.samefile(first_path, second_path)
    except (FileNotFoundError, OSError):
        return False


def stage_file_backup(path):
    """Copy an existing destination byte-for-byte to a temporary sibling file."""
    directory = os.path.dirname(os.path.abspath(path))
    prefix = f".{os.path.basename(path)}."
    fd, backup_path = tempfile.mkstemp(prefix=prefix, suffix='.backup', dir=directory)
    try:
        with open(path, 'rb') as source, os.fdopen(fd, 'wb') as backup:
            shutil.copyfileobj(source, backup)
            backup.flush()
            os.fsync(backup.fileno())
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(backup_path)
        except OSError:
            pass
        raise
    return backup_path


def save_json_pair(
    items_path,
    items_data,
    sources_path,
    sources_data,
    *,
    require_existing_valid=False,
):
    """Stage and commit two documents, rolling items back if sources fail."""
    validate_document_structure(items_data, "Items")
    validate_document_structure(sources_data, "Sources")
    if paths_refer_to_same_file(items_path, sources_path):
        raise ValueError("Items and sources must use different files.")

    with SAVE_LOCK:
        if require_existing_valid:
            load_json(items_path)
            load_json(sources_path)

        items_existed = os.path.exists(items_path)
        staged_items = None
        staged_sources = None
        items_backup = None
        preserve_items_backup = False

        try:
            staged_items = stage_json(items_path, items_data)
            staged_sources = stage_json(sources_path, sources_data)
            if items_existed:
                items_backup = stage_file_backup(items_path)

            os.replace(staged_items, items_path)
            staged_items = None
            try:
                os.replace(staged_sources, sources_path)
                staged_sources = None
            except Exception as commit_error:
                try:
                    if items_existed:
                        os.replace(items_backup, items_path)
                        items_backup = None
                    else:
                        os.unlink(items_path)
                except Exception as rollback_error:
                    if items_backup:
                        preserve_items_backup = True
                        raise RuntimeError(
                            f"Sources save failed and items rollback also failed; "
                            f"the items backup remains at {items_backup}: {rollback_error}"
                        ) from commit_error
                    raise RuntimeError(
                        f"Sources save failed and removal of the newly-created items file "
                        f"also failed; it may remain at {items_path}: {rollback_error}"
                    ) from commit_error
                raise
        finally:
            cleanup_paths = (
                staged_items,
                staged_sources,
                None if preserve_items_backup else items_backup,
            )
            for tmp_path in cleanup_paths:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

def load_config():
    """Load machine-local Scribity settings, falling back to portable defaults."""
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config if isinstance(config, dict) else {}
    except Exception as e:
        print(f"Could not read config at {CONFIG_PATH}: {e}")
        return {}

def save_config():
    """Persist the currently selected item/source files for the next launch."""
    save_json(CONFIG_PATH, {
        "items_path": ITEMS_PATH,
        "sources_path": SOURCES_PATH,
    })

def restore_last_used_paths():
    """Restore last-used files if a local config exists."""
    global ITEMS_PATH, SOURCES_PATH
    config = load_config()
    items_path = config.get("items_path")
    sources_path = config.get("sources_path")
    if isinstance(items_path, str) and items_path:
        ITEMS_PATH = items_path
    if isinstance(sources_path, str) and sources_path:
        SOURCES_PATH = sources_path

restore_last_used_paths()

@app.route('/')
def index():
    if not os.path.exists(HTML_PATH):
        return f"Error: Could not find {HTML_FILE} in {BASE_DIR}", 404
    return send_file(HTML_PATH)

@app.route('/api/data', methods=['GET'])
def get_all_data():
    """Returns both Items and Sources in one call"""
    global ITEMS_READY, SOURCES_READY
    with SAVE_LOCK:
        ITEMS_READY = False
        SOURCES_READY = False

        try:
            items = normalize_items(load_json(ITEMS_PATH))
        except JsonDocumentError as error:
            return json_document_error_response(error, "items")

        try:
            sources = load_json(SOURCES_PATH)
        except JsonDocumentError as error:
            return json_document_error_response(error, "sources")

        ITEMS_READY = True
        SOURCES_READY = True
        return jsonify({
            "status": "success",
            "items": items,
            "sources": sources,
            "items_filename": os.path.basename(ITEMS_PATH),
            "sources_filename": os.path.basename(SOURCES_PATH),
            "items_document": current_document_state("items"),
            "sources_document": current_document_state("sources"),
        })

# --- OPEN FILE PICKERS ---

@app.route('/api/open_items', methods=['POST'])
def open_items_picker():
    global ITEMS_PATH, ITEMS_READY
    
    if not TK_AVAILABLE:
         return jsonify({"status": "gui_unavailable", "message": "Tkinter not found"})

    try:
        root = tk.Tk()
        root.withdraw() 
        root.wm_attributes('-topmost', 1) 
        try:
             # Try to force focus on Mac
             os.system('''/usr/bin/osascript -e 'tell app "Finder" to set frontmost of process "Python" to true' ''')
        except:
             pass

        file_path = filedialog.askopenfilename(
            initialdir=os.path.dirname(ITEMS_PATH) if os.path.exists(ITEMS_PATH) else BASE_DIR,
            title="Select Items JSON File",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*"))
        )
        root.destroy()

        if file_path:
            data = load_json(file_path)
            with SAVE_LOCK:
                ITEMS_PATH = file_path
                ITEMS_READY = True
                document = reset_document_state("items")
                print(f"Switched Items file to: {ITEMS_PATH}")
                save_config()
                return jsonify({
                    "status": "success",
                    "filename": os.path.basename(ITEMS_PATH),
                    "data": data,
                    "document": document,
                })
        else:
            return jsonify({"status": "canceled"})

    except JsonDocumentError as error:
        return json_document_error_response(error, "items")
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/open_sources', methods=['POST'])
def open_sources_picker():
    global SOURCES_PATH, SOURCES_READY
    
    if not TK_AVAILABLE:
         return jsonify({"status": "gui_unavailable", "message": "Tkinter not found"})

    try:
        root = tk.Tk()
        root.withdraw() 
        root.wm_attributes('-topmost', 1) 
        try:
             os.system('''/usr/bin/osascript -e 'tell app "Finder" to set frontmost of process "Python" to true' ''')
        except:
             pass

        file_path = filedialog.askopenfilename(
            initialdir=os.path.dirname(SOURCES_PATH) if os.path.exists(SOURCES_PATH) else BASE_DIR,
            title="Select Sources JSON File",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*"))
        )
        root.destroy()

        if file_path:
            data = load_json(file_path)
            with SAVE_LOCK:
                SOURCES_PATH = file_path
                SOURCES_READY = True
                document = reset_document_state("sources")
                print(f"Switched Sources file to: {SOURCES_PATH}")
                save_config()
                return jsonify({
                    "status": "success",
                    "filename": os.path.basename(SOURCES_PATH),
                    "data": data,
                    "document": document,
                })
        else:
            return jsonify({"status": "canceled"})

    except JsonDocumentError as error:
        return json_document_error_response(error, "sources")
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

# --- MANUAL PATH SWITCH ENDPOINTS (fallback when Tkinter unavailable) ---

@app.route('/api/switch_items', methods=['POST'])
def switch_items_manual():
    global ITEMS_PATH, ITEMS_READY
    try:
        new_path = request.json.get('path')
        if not new_path:
            return jsonify({"status": "error", "message": "No path provided"})
        
        data = load_json(new_path)
        with SAVE_LOCK:
            ITEMS_PATH = new_path
            ITEMS_READY = True
            document = reset_document_state("items")
            print(f"Switched Items file to: {ITEMS_PATH}")
            save_config()
            return jsonify({
                "status": "success",
                "filename": os.path.basename(ITEMS_PATH),
                "data": data,
                "document": document,
            })
    except JsonDocumentError as error:
        return json_document_error_response(error, "items")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/switch_sources', methods=['POST'])
def switch_sources_manual():
    global SOURCES_PATH, SOURCES_READY
    try:
        new_path = request.json.get('path')
        if not new_path:
            return jsonify({"status": "error", "message": "No path provided"})
        
        data = load_json(new_path)
        with SAVE_LOCK:
            SOURCES_PATH = new_path
            SOURCES_READY = True
            document = reset_document_state("sources")
            print(f"Switched Sources file to: {SOURCES_PATH}")
            save_config()
            return jsonify({
                "status": "success",
                "filename": os.path.basename(SOURCES_PATH),
                "data": data,
                "document": document,
            })
    except JsonDocumentError as error:
        return json_document_error_response(error, "sources")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- SAVE ENDPOINTS ---

@app.route('/api/save_items', methods=['POST'])
def save_items_endpoint():
    with SAVE_LOCK:
        if not ITEMS_READY:
            return jsonify({
                "status": "error",
                "kind": "document_not_ready",
                "document": "items",
                "message": "Items were not saved because no valid items document is loaded.",
            }), 409
    payload = request.get_json(silent=True)
    new_data = payload.get("data") if isinstance(payload, dict) else None
    try:
        validate_document_structure(new_data, "Items")
    except JsonDocumentShapeError as error:
        return invalid_document_shape_response(error, "items")
    with SAVE_LOCK:
        if not ITEMS_READY:
            return jsonify({
                "status": "error",
                "kind": "document_not_ready",
                "document": "items",
                "message": "Items were not saved because no valid items document is loaded.",
            }), 409
        supplied_document = {
            "token": payload.get("document_token"),
            "revision": payload.get("revision"),
        }
        if not document_request_is_current("items", supplied_document):
            return stale_document_response("items")
        try:
            save_json(ITEMS_PATH, new_data)
            document = advance_document_revision("items")
            return jsonify({
                "status": "success",
                "message": "Items saved",
                "document": document,
            })
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_sources', methods=['POST'])
def save_sources_endpoint():
    with SAVE_LOCK:
        if not SOURCES_READY:
            return jsonify({
                "status": "error",
                "kind": "document_not_ready",
                "document": "sources",
                "message": "Sources were not saved because no valid sources document is loaded.",
            }), 409
    payload = request.get_json(silent=True)
    new_data = payload.get("data") if isinstance(payload, dict) else None
    try:
        validate_document_structure(new_data, "Sources")
    except JsonDocumentShapeError as error:
        return invalid_document_shape_response(error, "sources")
    with SAVE_LOCK:
        if not SOURCES_READY:
            return jsonify({
                "status": "error",
                "kind": "document_not_ready",
                "document": "sources",
                "message": "Sources were not saved because no valid sources document is loaded.",
            }), 409
        supplied_document = {
            "token": payload.get("document_token"),
            "revision": payload.get("revision"),
        }
        if not document_request_is_current("sources", supplied_document):
            return stale_document_response("sources")
        try:
            save_json(SOURCES_PATH, new_data)
            document = advance_document_revision("sources")
            return jsonify({
                "status": "success",
                "message": "Sources saved",
                "document": document,
            })
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/append_import', methods=['POST'])
def append_import():
    """Persist the post-import item and source snapshots as one operation."""
    if not ITEMS_READY or not SOURCES_READY:
        return jsonify({
            "status": "error",
            "kind": "document_not_ready",
            "message": "Open valid items and sources documents before appending an import.",
        }), 409

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "Expected a JSON object."}), 400

    items_data = payload.get('items')
    sources_data = payload.get('sources')
    for name, data in (("items", items_data), ("sources", sources_data)):
        try:
            validate_document_structure(data, name.capitalize())
        except JsonDocumentShapeError as error:
            return invalid_document_shape_response(error, name)

    imported_sources = payload.get('imported_sources')
    if imported_sources is not None:
        try:
            validate_document_structure(imported_sources, "Imported sources")
        except JsonDocumentShapeError as error:
            return invalid_document_shape_response(error, "imported_sources")

    with SAVE_LOCK:
        if not ITEMS_READY or not SOURCES_READY:
            return jsonify({
                "status": "error",
                "kind": "document_not_ready",
                "message": "Open valid items and sources documents before appending an import.",
            }), 409
        if not document_request_is_current("items", payload.get("items_document")):
            return stale_document_response("items")
        if not document_request_is_current("sources", payload.get("sources_document")):
            return stale_document_response("sources")

        if imported_sources is not None:
            try:
                existing_sources = load_json(SOURCES_PATH)
            except JsonDocumentError as error:
                return json_document_error_response(error, "sources")

            collision_ids = find_source_id_collisions(existing_sources, imported_sources)
            if collision_ids:
                return jsonify({
                    "status": "error",
                    "kind": "source_id_collision",
                    "source_ids": collision_ids,
                    "message": (
                        "Append stopped because imported source IDs conflict: "
                        + ", ".join(collision_ids)
                    ),
                }), 409

        try:
            save_json_pair(
                ITEMS_PATH,
                items_data,
                SOURCES_PATH,
                sources_data,
                require_existing_valid=True,
            )
            return jsonify({
                "status": "success",
                "message": "Import appended",
                "items_count": len(items_data),
                "sources_count": len(sources_data),
                "items_document": advance_document_revision("items"),
                "sources_document": advance_document_revision("sources"),
            })
        except (JsonDocumentError, ValueError) as error:
            return jsonify({"status": "error", "message": str(error)}), 409
        except Exception as error:
            return jsonify({"status": "error", "message": str(error)}), 500

# --- SAVE AS ENDPOINTS ---

@app.route('/api/save_items_as', methods=['POST'])
def save_items_as():
    global ITEMS_PATH, ITEMS_READY
    payload = request.get_json(silent=True)
    new_data = payload.get('data') if isinstance(payload, dict) else None
    try:
        validate_document_structure(new_data, "Items")
    except JsonDocumentShapeError as error:
        return invalid_document_shape_response(error, "items")
    supplied_document = {
        "token": payload.get("document_token"),
        "revision": payload.get("revision"),
    }
    with SAVE_LOCK:
        if not document_request_is_current("items", supplied_document):
            return stale_document_response("items")
    if not TK_AVAILABLE:
        return jsonify({"status": "gui_unavailable", "message": "Tkinter not found"})
    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)
        file_path = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(ITEMS_PATH),
            initialfile=os.path.basename(ITEMS_PATH),
            title="Save Items As",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
            defaultextension=".json"
        )
        root.destroy()
        if file_path:
            with SAVE_LOCK:
                if not document_request_is_current("items", supplied_document):
                    return stale_document_response("items")
                save_json(file_path, new_data)
                ITEMS_PATH = file_path
                ITEMS_READY = True
                document = reset_document_state("items")
                save_config()
                print(f"Saved Items As: {ITEMS_PATH}")
                return jsonify({
                    "status": "success",
                    "filename": os.path.basename(file_path),
                    "document": document,
                })
        return jsonify({"status": "canceled"})
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_sources_as', methods=['POST'])
def save_sources_as():
    global SOURCES_PATH, SOURCES_READY
    payload = request.get_json(silent=True)
    new_data = payload.get('data') if isinstance(payload, dict) else None
    try:
        validate_document_structure(new_data, "Sources")
    except JsonDocumentShapeError as error:
        return invalid_document_shape_response(error, "sources")
    supplied_document = {
        "token": payload.get("document_token"),
        "revision": payload.get("revision"),
    }
    with SAVE_LOCK:
        if not document_request_is_current("sources", supplied_document):
            return stale_document_response("sources")
    if not TK_AVAILABLE:
        return jsonify({"status": "gui_unavailable", "message": "Tkinter not found"})
    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)
        file_path = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(SOURCES_PATH),
            initialfile=os.path.basename(SOURCES_PATH),
            title="Save Sources As",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
            defaultextension=".json"
        )
        root.destroy()
        if file_path:
            with SAVE_LOCK:
                if not document_request_is_current("sources", supplied_document):
                    return stale_document_response("sources")
                save_json(file_path, new_data)
                SOURCES_PATH = file_path
                SOURCES_READY = True
                document = reset_document_state("sources")
                save_config()
                print(f"Saved Sources As: {SOURCES_PATH}")
                return jsonify({
                    "status": "success",
                    "filename": os.path.basename(file_path),
                    "document": document,
                })
        return jsonify({"status": "canceled"})
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

# --- NEW EMPTY DOCUMENT ---

@app.route('/api/new_document', methods=['POST'])
def new_document():
    """Open two save-as dialogs, write empty JSON arrays to both paths,
    then switch globals — both or neither (cancel-safe)."""
    global ITEMS_PATH, SOURCES_PATH, ITEMS_READY, SOURCES_READY
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "Expected a JSON object."}), 400
    with SAVE_LOCK:
        if not document_request_is_current("items", payload.get("items_document")):
            return stale_document_response("items")
        if not document_request_is_current("sources", payload.get("sources_document")):
            return stale_document_response("sources")
    if not TK_AVAILABLE:
        return jsonify({"status": "gui_unavailable", "message": "Tkinter not found"})
    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)

        items_path = filedialog.asksaveasfilename(
            initialdir=BASE_DIR,
            initialfile='items.json',
            title="New Document — Save Items As (1 of 2)",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
            defaultextension=".json"
        )
        if not items_path:
            root.destroy()
            return jsonify({"status": "canceled"})

        sources_path = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(items_path),
            initialfile='sources.json',
            title="New Document — Save Sources As (2 of 2)",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
            defaultextension=".json"
        )
        root.destroy()
        if not sources_path:
            return jsonify({"status": "canceled"})

        with SAVE_LOCK:
            if not document_request_is_current("items", payload.get("items_document")):
                return stale_document_response("items")
            if not document_request_is_current("sources", payload.get("sources_document")):
                return stale_document_response("sources")
            # Commit both empty documents, then update globals.
            save_json_pair(items_path, [], sources_path, [])
            ITEMS_PATH   = items_path
            SOURCES_PATH = sources_path
            ITEMS_READY = True
            SOURCES_READY = True
            items_document = reset_document_state("items")
            sources_document = reset_document_state("sources")
            save_config()
            print(f"New empty document created — Items: {ITEMS_PATH} | Sources: {SOURCES_PATH}")

            return jsonify({
                "status": "success",
                "items_filename":   os.path.basename(items_path),
                "sources_filename": os.path.basename(sources_path),
                "items_document": items_document,
                "sources_document": sources_document,
            })
    except ValueError as e:
        return jsonify({
            "status": "error",
            "kind": "path_conflict",
            "message": str(e),
        }), 409
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

# --- SAVE NEW DOCUMENT (atomic: both files or neither path is updated) ---

@app.route('/api/save_new_document', methods=['POST'])
def save_new_document():
    """Open two save dialogs, write both files, then update both globals.
    Globals only mutate if BOTH saves succeed — no split-state on cancel or error."""
    global ITEMS_PATH, SOURCES_PATH, ITEMS_READY, SOURCES_READY
    payload = request.get_json(silent=True)
    items_data = payload.get('items') if isinstance(payload, dict) else None
    sources_data = payload.get('sources') if isinstance(payload, dict) else None
    for name, data in (("items", items_data), ("sources", sources_data)):
        try:
            validate_document_structure(data, name.capitalize())
        except JsonDocumentShapeError as error:
            return invalid_document_shape_response(error, name)
    with SAVE_LOCK:
        if not document_request_is_current("items", payload.get("items_document")):
            return stale_document_response("items")
        if not document_request_is_current("sources", payload.get("sources_document")):
            return stale_document_response("sources")
    if not TK_AVAILABLE:
        return jsonify({"status": "gui_unavailable", "message": "Tkinter not found"})
    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)

        # Dialog 1 of 2 — items file
        items_path = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(ITEMS_PATH) if os.path.exists(ITEMS_PATH) else BASE_DIR,
            initialfile=os.path.basename(ITEMS_PATH),
            title="Save Items As (1 of 2)",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
            defaultextension=".json"
        )
        if not items_path:
            root.destroy()
            return jsonify({"status": "canceled"})

        # Dialog 2 of 2 — sources file
        sources_path = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(SOURCES_PATH) if os.path.exists(SOURCES_PATH) else BASE_DIR,
            initialfile=os.path.basename(SOURCES_PATH),
            title="Save Sources As (2 of 2)",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
            defaultextension=".json"
        )
        root.destroy()
        if not sources_path:
            return jsonify({"status": "canceled"})

        with SAVE_LOCK:
            if not document_request_is_current("items", payload.get("items_document")):
                return stale_document_response("items")
            if not document_request_is_current("sources", payload.get("sources_document")):
                return stale_document_response("sources")
            # Both paths confirmed — commit both files, THEN update globals.
            save_json_pair(items_path, items_data, sources_path, sources_data)
            ITEMS_PATH   = items_path
            SOURCES_PATH = sources_path
            ITEMS_READY = True
            SOURCES_READY = True
            items_document = reset_document_state("items")
            sources_document = reset_document_state("sources")
            save_config()
            print(f"New document saved — Items: {ITEMS_PATH} | Sources: {SOURCES_PATH}")

            return jsonify({
                "status": "success",
                "items_filename":   os.path.basename(items_path),
                "sources_filename": os.path.basename(sources_path),
                "items_document": items_document,
                "sources_document": sources_document,
            })
    except ValueError as e:
        return jsonify({
            "status": "error",
            "kind": "path_conflict",
            "message": str(e),
        }), 409
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

# --- DRR PARSER ENDPOINTS ---


try:
    from parse_drr import parse_mdx_file, parse_mdx_folder
    DRR_PARSER_AVAILABLE = True
except ImportError:
    DRR_PARSER_AVAILABLE = False

@app.route('/api/parse_drr_picker', methods=['POST'])
def parse_drr_picker():
    """Open a file/folder picker for DRR reports, then parse.
    Accepts { mode: 'file' | 'folder' }."""
    if not DRR_PARSER_AVAILABLE:
        return jsonify({"status": "error", "message": "parse_drr module not found"}), 500
    if not TK_AVAILABLE:
        return jsonify({"status": "gui_unavailable", "message": "Tkinter not found"})
    try:
        mode = request.json.get('mode', 'file')
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)
        try:
            os.system('''/usr/bin/osascript -e 'tell app "Finder" to set frontmost of process "Python" to true' ''')
        except:
            pass

        if mode == 'folder':
            selected = filedialog.askdirectory(
                title="Select folder containing .mdx DRR reports"
            )
        else:
            selected = filedialog.askopenfilename(
                title="Select DRR Report (.mdx)",
                filetypes=(("MDX files", "*.mdx"), ("All files", "*.*"))
            )
        root.destroy()

        if not selected:
            return jsonify({"status": "canceled"})

        if os.path.isdir(selected):
            result = parse_mdx_folder(selected)
        else:
            result = parse_mdx_file(selected)

        return jsonify({"status": "success", "selected_path": selected, **result})
    except Exception as e:
        print(f"DRR picker error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    print(f"--- SCRIBITY SERVER RUNNING ---")
    print(f"Server: http://localhost:{PORT}")
    print(f"Initial Items File: {ITEMS_PATH}")
    print(f"Initial Sources File: {SOURCES_PATH}")
    if not TK_AVAILABLE:
        print("Note: Tkinter not found. File picker will not work (install python-tk).")
    if DRR_PARSER_AVAILABLE:
        print("DRR Parser: Available")
    else:
        print("DRR Parser: NOT FOUND (parse_drr.py missing)")
    app.run(**server_run_options())
