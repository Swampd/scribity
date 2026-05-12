"""
Scribity Server — py scribity_server.py

"""
# py "scribity_server.py"

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

# Default file paths — relative to the server script.
# Use the file picker (Items/Sources buttons) to load a different file.
ITEMS_PATH   = os.path.join(BASE_DIR, 'items.json')
SOURCES_PATH = os.path.join(BASE_DIR, 'sources.json')

app = Flask(__name__)
CORS(app)

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

def load_json(path, template, default_init=None):
    """Generic JSON loader with template fallback"""
    if not os.path.exists(path):
        print(f"Creating new file at: {path}")
        data = default_init if default_init else []
        save_json(path, data)
        return data
    
    with open(path, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"\n!!! JSON PARSE ERROR in {path}: {e}\n!!! Returning empty list — file may be corrupted!\n")
            return []

def save_json(path, data):
    """Generic JSON saver with atomic write to prevent corruption."""
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    # Atomic rename (overwrites existing file)
    os.replace(tmp_path, path)

@app.route('/')
def index():
    if not os.path.exists(HTML_PATH):
        return f"Error: Could not find {HTML_FILE} in {BASE_DIR}", 404
    return send_file(HTML_PATH)

@app.route('/api/data', methods=['GET'])
def get_all_data():
    """Returns both Items and Sources in one call"""
    items = load_json(ITEMS_PATH, ITEM_TEMPLATE, default_init=[{**ITEM_TEMPLATE, "id_item": "1", "quote_original": "Welcome to the new system.", "rule_number": ["General"]}])
    items = normalize_items(items)
    sources = load_json(SOURCES_PATH, SOURCE_TEMPLATE, default_init=[{**SOURCE_TEMPLATE, "id_source": "src_1", "short_cite": "Manual, 2026", "title": "System Manual"}])
    
    return jsonify({
        "items": items,
        "sources": sources,
        "items_filename": os.path.basename(ITEMS_PATH),
        "sources_filename": os.path.basename(SOURCES_PATH)
    })

# --- OPEN FILE PICKERS ---

@app.route('/api/open_items', methods=['POST'])
def open_items_picker():
    global ITEMS_PATH
    
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
            ITEMS_PATH = file_path
            print(f"Switched Items file to: {ITEMS_PATH}")
            data = load_json(ITEMS_PATH, ITEM_TEMPLATE)
            return jsonify({
                "status": "success", 
                "filename": os.path.basename(ITEMS_PATH),
                "data": data
            })
        else:
            return jsonify({"status": "canceled"})

    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/open_sources', methods=['POST'])
def open_sources_picker():
    global SOURCES_PATH
    
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
            SOURCES_PATH = file_path
            print(f"Switched Sources file to: {SOURCES_PATH}")
            data = load_json(SOURCES_PATH, SOURCE_TEMPLATE)
            return jsonify({
                "status": "success", 
                "filename": os.path.basename(SOURCES_PATH),
                "data": data
            })
        else:
            return jsonify({"status": "canceled"})

    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

# --- MANUAL PATH SWITCH ENDPOINTS (fallback when Tkinter unavailable) ---

@app.route('/api/switch_items', methods=['POST'])
def switch_items_manual():
    global ITEMS_PATH
    try:
        new_path = request.json.get('path')
        if not new_path:
            return jsonify({"status": "error", "message": "No path provided"})
        
        ITEMS_PATH = new_path
        print(f"Switched Items file to: {ITEMS_PATH}")
        data = load_json(ITEMS_PATH, ITEM_TEMPLATE)
        return jsonify({
            "status": "success", 
            "filename": os.path.basename(ITEMS_PATH),
            "data": data
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/switch_sources', methods=['POST'])
def switch_sources_manual():
    global SOURCES_PATH
    try:
        new_path = request.json.get('path')
        if not new_path:
            return jsonify({"status": "error", "message": "No path provided"})
        
        SOURCES_PATH = new_path
        print(f"Switched Sources file to: {SOURCES_PATH}")
        data = load_json(SOURCES_PATH, SOURCE_TEMPLATE)
        return jsonify({
            "status": "success", 
            "filename": os.path.basename(SOURCES_PATH),
            "data": data
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- SAVE ENDPOINTS ---

@app.route('/api/save_items', methods=['POST'])
def save_items_endpoint():
    try:
        new_data = request.json
        # Saves to whatever the current ITEMS_PATH is (default or user-selected)
        save_json(ITEMS_PATH, new_data)
        return jsonify({"status": "success", "message": "Items saved"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_sources', methods=['POST'])
def save_sources_endpoint():
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
    global ITEMS_PATH
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
            print(f"Saved Items As: {ITEMS_PATH}")
            return jsonify({"status": "success", "filename": os.path.basename(file_path)})
        return jsonify({"status": "canceled"})
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_sources_as', methods=['POST'])
def save_sources_as():
    global SOURCES_PATH
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
    global ITEMS_PATH, SOURCES_PATH
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
    global ITEMS_PATH, SOURCES_PATH
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

@app.route('/api/parse_drr', methods=['POST'])
def parse_drr_endpoint():
    """Parse a DRR .mdx file or folder. Accepts { path: '...' }.
    Returns parsed items and sources for preview before import."""
    if not DRR_PARSER_AVAILABLE:
        return jsonify({"status": "error", "message": "parse_drr module not found"}), 500
    try:
        target_path = request.json.get('path', '')
        if not target_path or not os.path.exists(target_path):
            return jsonify({"status": "error", "message": f"Path not found: {target_path}"}), 400

        if os.path.isdir(target_path):
            result = parse_mdx_folder(target_path)
        else:
            result = parse_mdx_file(target_path)

        return jsonify({"status": "success", **result})
    except Exception as e:
        print(f"DRR parse error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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