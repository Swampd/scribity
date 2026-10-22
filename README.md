# Scribity

**A local-first research and writing workspace for organizing sources, structuring evidence, and drafting source-backed narratives.**

![Scribity library view](docs/images/scribity-library.png)

> **Project status:** Active development. Scribity is usable today, but its interface and document formats may continue to evolve.

Scribity keeps research documents on the user's computer and combines source management, evidence organization, drafting, and import tools in one focused workspace. It supports both general research projects and a specialized rule-and-example workflow originally designed for instructional writing.

## Highlights

- One editable JSON project contains items, sources, and project metadata.
- Items link directly to structured source records.
- Categories, subparts, tags, filters, and a reorderable Stage help shape large collections of evidence.
- Draft and Render views turn selected material into an ordered narrative.
- An MDX parser previews structured report imports before saving them.
- Optimistic document revisions reject stale saves from old tabs or previously opened files.
- Unified project saves validate both lists and publish one atomic file replacement; legacy pair support remains available for conversion.
- Undo history and delayed saves are isolated when switching documents.
- macOS and Windows launchers are included.

## Technology

- Python and Flask for the local server and file operations
- React 18, Tailwind CSS, and Lucide for the browser interface
- Python `unittest` and Playwright for automated regression coverage
- JSON documents for portable, inspectable storage

Scribity is intentionally small and local: there is no account system, hosted database, analytics service, or cloud synchronization layer.

## Quick start

Requirements:

- Python 3.10 or newer
- A current desktop browser
- Node.js only if you want to run the browser tests

```bash
git clone https://github.com/Swampd/scribity.git
cd scribity
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python start_scribity.py
```

On Windows, activate the environment with `.venv\Scripts\activate` and run `python start_scribity.py`. The included `scribity.command` and `scribity.bat` launchers are also available for macOS and Windows.

Once dependencies are installed in `.venv`, `scribity.bat` uses `.venv\Scripts\python.exe` automatically; activation is not required when double-clicking it. `start_scribity.py` also prefers the project's `.venv` interpreter on Windows, macOS, and Linux.

Scribity opens at [http://localhost:8000](http://localhost:8000). To explore without personal data, use **+ New → Import legacy items/sources pair…**, select the two example files below, and save a new project JSON:

- Items: `examples/research-items.json`
- Sources: `examples/research-sources.json`

The `examples/` directory also includes an improv-oriented document pair. Every included example record is synthetic and exists only to demonstrate the interface.

## How documents work

Use **Open Project** to load one versioned JSON containing two related arrays:

| Document | Purpose |
| --- | --- |
| Items | Quotations, notes, examples, categories, ordering, and drafting metadata |
| Sources | Bibliographic and reference information linked through `id_source` |

Use **Convert loaded pair** for the pair already open, or **+ New → Import legacy items/sources pair…** for another pair. Conversion creates and opens a new file; original files are never overwritten. **+ New → New Project** creates an empty project. **Save As…** saves and opens a new copy. Choose a new filename; autosave updates the current file.

See [the project JSON format](docs/PROJECT_JSON.md) for the envelope, manual editing, preservation rules, and known limitations. Restart the server after updating to load the project endpoints.

Starter structures are available in `schema_research_items.json`, `schema_improv_items.json`, and `schema_sources.json`. Default working filenames and `scribity_config.json` are ignored by Git. Store custom-named research projects outside the code checkout, or add their paths to your local ignore list.

## Data-safety design

The application treats document integrity as a first-class concern:

1. Projects validate their format/version, both record lists, and stable unique identities.
2. Every unified project receives one shared opaque token and revision.
3. Saves from an old document or stale browser tab are rejected.
4. Delayed edits are flushed before a document switch completes.
5. A unified project updates both lists in one atomic file replacement. Legacy pair operations retain their paired-write protections.

These safeguards are covered by server, parser, document-session, accessibility, and browser-interaction tests.

## Testing

Run the Python suite:

```bash
python3 -B -m unittest discover
```

Run the browser suite:

```bash
npm install
npx playwright install chromium
npm run test:e2e
```

The Playwright suite serves the dashboard locally and uses in-memory API responses; it does not open or modify configured research documents. See [TESTING.md](TESTING.md) for details.

## Privacy

Scribity does not upload document contents. File selection, parsing, and saves happen through the local Flask server. The following local files are intentionally excluded from version control:

- `items.json`
- `sources.json`
- `scribity_config.json`
- temporary JSON writes and browser-test output

Before sharing a fork, review its complete Git history as well as its current files; deleting sensitive content in a later commit does not remove it from earlier commits.

## Copyright

Copyright © 2026 Casey Auttonberry. All rights reserved.

No open-source license is granted for Scribity at this time. The source is visible for portfolio and evaluation purposes; see [COPYRIGHT.md](COPYRIGHT.md) for details. Third-party libraries remain subject to their respective licenses.

### Create an episode project from selected research

For the episode-selection workflow, open **Draft → Create project from Draft**.
Your existing Draft is already the selection; you do not need to check cards.
The copied research goes into the new project’s Library, with an empty Draft
ready for a fresh story order. The original project and Draft remain intact.

You can also use **+ New → Create project from selection**. Choose the entire current Draft,
checked Library items (including checks hidden by filters), or current filtered
Library results. The dialog describes the scope; Draft selection ignores search,
category, quick filters, and the Draft part filter. Supporting descendants are
always included recursively, even when their `id_script` is zero.

1. Choose **Start with an empty Draft** (default) or **Preserve existing Draft
   order**. Empty resets only `id_script`; preserve retains existing values and
   never adds otherwise undrafted items to Draft.
2. Click **Preview project**. Pending edits are saved first. Review selected,
   additional supporting, total item, and source counts, plus any relationship
   notices. No relevance filtering or narrative reordering is performed.
3. Click **Save new project…** and choose one new JSON filename, or enter an absolute path in an existing folder. Existing files cannot be overwritten. Canceling leaves the original project active.
4. After saving, choose **Open new project**, or **Done — keep original open**. Opening loads both lists together and remembers the project for next launch. Rendered script exports remain separate.

Research fields, IDs, notes, citations, category order, tags, script parts, and
unknown metadata are copied. `nested_under` is the structural support link.
Selected children whose parents are absent become top-level items in the copy;
the original link is recorded in `_scribity_external_references`. Item links in
`related_facts`, `supports`, and `contradicts` that point outside the copy (or are
unresolved) are likewise moved into that provenance list and disclosed in the
preview. Parser-generated `grp_*` multi-citation group labels stay intact; they
do not expand the selection. Generic extra-ID fields and other metadata remain
opaque and unchanged. Warnings must be acknowledged before saving.

Missing referenced source records, conflicting duplicate source IDs, support
cycles, and ambiguous item IDs block extraction with an explanation. Identical
source duplicates are included once. Blank source IDs remain blank. Source
bibliography links and URLs are preserved without pulling in unrelated records.

Previews expire after 30 minutes or a server restart (at most 16 are retained).
Edits, file switches, or external file changes invalidate an unsaved preview;
create a fresh one. Saved files remain available after a preview expires and can
be opened through **Open Project**. Publication uses atomic
no-overwrite hard links to staged files; a filesystem without hard-link support
will fail safely, in which case save to a local folder that supports them.

### Import metadata-bearing research reports

Use **Parser** to preview an MDX report or a folder. Report metadata is preserved
on imported items and sources, including through Save As and episode-project
extraction. Publication dates no longer populate historical event dates.

The preview shows explicit errors for missing citations and content it cannot
extract; these errors block saving. Already imported report IDs block duplicate
appends. [The report format guide](docs/DRR_IMPORT_FORMAT.md) includes a small
sample report, expected output, supported formatting, and current limitations.
After updating, install `requirements.txt` and restart Scribity for the new
importer to load. Existing research files are not migrated automatically.

### Undo and redo

Use the visible **Undo** and **Redo** buttons, or **⌘Z / Ctrl+Z** to undo and
**⌘Shift+Z / Ctrl+Shift+Z** to redo. **Ctrl+Y** also redoes a change.
While typing in a text field, the browser retains its own text undo behavior;
click outside the field or use the toolbar for document-level undo.

Unified projects have one history across item and source actions, including imports that change both lists. Up to 30 actions are retained for the current session. Delayed Inspector, Draft/Render, example-note, and source edits are included. Undo cancels pending edit timers before restoring both lists. New edits clear redo. Opening another project clears history; Save As preserves it. Reloading clears history. Restored states use the same full-project save queue.

Unconverted legacy pairs retain their previous separate item/source histories until conversion.
