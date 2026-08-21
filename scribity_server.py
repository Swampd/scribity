"""
Scribity Server — py scribity_server.py

"""

import json
import os
import sys
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

    if not isinstance(data, list):
        raise JsonDocumentError(
            "invalid_shape",
            path,
            f"{os.path.basename(path)} must contain a JSON array.",
            422,
        )
    if any(not isinstance(entry, dict) for entry in data):
        raise JsonDocumentError(
            "invalid_shape",
            path,
            f"Every entry in {os.path.basename(path)} must be a JSON object.",
            422,
        )

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
    }), error.status_code

def save_json(path, data):
    """Generic JSON saver with atomic write to prevent corruption."""
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    # Atomic rename (overwrites existing file)
    os.replace(tmp_path, path)

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
        "sources_filename": os.path.basename(SOURCES_PATH)
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
            ITEMS_PATH = file_path
            ITEMS_READY = True
            print(f"Switched Items file to: {ITEMS_PATH}")
            save_config()
            return jsonify({
                "status": "success", 
                "filename": os.path.basename(ITEMS_PATH),
                "data": data
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
            SOURCES_PATH = file_path
            SOURCES_READY = True
            print(f"Switched Sources file to: {SOURCES_PATH}")
            save_config()
            return jsonify({
                "status": "success", 
                "filename": os.path.basename(SOURCES_PATH),
                "data": data
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
        ITEMS_PATH = new_path
        ITEMS_READY = True
        print(f"Switched Items file to: {ITEMS_PATH}")
        save_config()
        return jsonify({
            "status": "success", 
            "filename": os.path.basename(ITEMS_PATH),
            "data": data
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
        SOURCES_PATH = new_path
        SOURCES_READY = True
        print(f"Switched Sources file to: {SOURCES_PATH}")
        save_config()
        return jsonify({
            "status": "success", 
            "filename": os.path.basename(SOURCES_PATH),
            "data": data
        })
    except JsonDocumentError as error:
        return json_document_error_response(error, "sources")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- SAVE ENDPOINTS ---

@app.route('/api/save_items', methods=['POST'])
def save_items_endpoint():
    if not ITEMS_READY:
        return jsonify({
            "status": "error",
            "kind": "document_not_ready",
            "document": "items",
            "message": "Items were not saved because no valid items document is loaded.",
        }), 409
    try:
        new_data = request.json
        # Saves to whatever the current ITEMS_PATH is (default or user-selected)
        save_json(ITEMS_PATH, new_data)
        return jsonify({"status": "success", "message": "Items saved"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_sources', methods=['POST'])
def save_sources_endpoint():
    if not SOURCES_READY:
        return jsonify({
            "status": "error",
            "kind": "document_not_ready",
            "document": "sources",
            "message": "Sources were not saved because no valid sources document is loaded.",
        }), 409
    try:
        new_data = request.json
        # Saves to whatever the current SOURCES_PATH is (default or user-selected)
        save_json(SOURCES_PATH, new_data)
        return jsonify({"status": "success", "message": "Sources saved"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- SAVE AS ENDPOINTS ---

@app.route('/api/save_items_as', methods=['POST'])
def save_items_as():
    global ITEMS_PATH, ITEMS_READY
    if not TK_AVAILABLE:
        return jsonify({"status": "gui_unavailable", "message": "Tkinter not found"})
    try:
        new_data = request.json.get('data', [])
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
            save_json(file_path, new_data)
            ITEMS_PATH = file_path
            ITEMS_READY = True
            save_config()
            print(f"Saved Items As: {ITEMS_PATH}")
            return jsonify({"status": "success", "filename": os.path.basename(file_path)})
        return jsonify({"status": "canceled"})
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_sources_as', methods=['POST'])
def save_sources_as():
    global SOURCES_PATH, SOURCES_READY
    if not TK_AVAILABLE:
        return jsonify({"status": "gui_unavailable", "message": "Tkinter not found"})
    try:
        new_data = request.json.get('data', [])
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
            save_json(file_path, new_data)
            SOURCES_PATH = file_path
            SOURCES_READY = True
            save_config()
            print(f"Saved Sources As: {SOURCES_PATH}")
            return jsonify({"status": "success", "filename": os.path.basename(file_path)})
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

        # Write empty arrays, then update globals
        save_json(items_path,   [])
        save_json(sources_path, [])
        ITEMS_PATH   = items_path
        SOURCES_PATH = sources_path
        ITEMS_READY = True
        SOURCES_READY = True
        save_config()
        print(f"New empty document created — Items: {ITEMS_PATH} | Sources: {SOURCES_PATH}")

        return jsonify({
            "status": "success",
            "items_filename":   os.path.basename(items_path),
            "sources_filename": os.path.basename(sources_path)
        })
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

# --- SAVE NEW DOCUMENT (atomic: both files or neither path is updated) ---

@app.route('/api/save_new_document', methods=['POST'])
def save_new_document():
    """Open two save dialogs, write both files, then update both globals.
    Globals only mutate if BOTH saves succeed — no split-state on cancel or error."""
    global ITEMS_PATH, SOURCES_PATH, ITEMS_READY, SOURCES_READY
    if not TK_AVAILABLE:
        return jsonify({"status": "gui_unavailable", "message": "Tkinter not found"})
    try:
        items_data  = request.json.get('items',   [])
        sources_data = request.json.get('sources', [])

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

        # Both paths confirmed — write files, THEN update globals
        save_json(items_path,   items_data)
        save_json(sources_path, sources_data)
        ITEMS_PATH   = items_path
        SOURCES_PATH = sources_path
        ITEMS_READY = True
        SOURCES_READY = True
        save_config()
        print(f"New document saved — Items: {ITEMS_PATH} | Sources: {SOURCES_PATH}")

        return jsonify({
            "status": "success",
            "items_filename":   os.path.basename(items_path),
            "sources_filename": os.path.basename(sources_path)
        })
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
    app.run(port=PORT, debug=True)
