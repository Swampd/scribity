# Scribity tests

The Python tests cover parser behavior, server data safety, launchers, and
dashboard structure:

```sh
python3 -B -m unittest discover
```

The separate Chromium suite exercises actual dashboard interactions and save
queue/document-switch behavior:

```sh
npm install
npx playwright install chromium
npm run test:e2e
```

The browser suite serves only `dashboard.html` on a random localhost port. Its
API and JSON documents are mocked in memory; it does not start the Scribity
server, load `scribity_config.json`, or touch your working documents. The app's
React/Babel/Tailwind/Lucide CDN scripts still require an internet connection.

Project extraction has fixture-only Python coverage in `test_project_extraction.py`
(recursive selection, metadata, source IDs, relationship repairs/errors, paired
writes, cancellation, opening, and stale sessions). It runs with the ordinary
Python suite. No tests use the configured research files.

The frontend extraction handlers and JSX syntax can also be checked without
browser automation:

```sh
npm run test:project-ui
```

These Node tests execute the actual dashboard handlers with in-memory API/state
stubs, including pending-save flushing, scope selection, cancellation, and
explicit pair activation. They do not verify rendered layout or native dialogs.

DRR compatibility and persistence tests use `tests/fixtures/drr/` and temporary
files. `test_drr_compatibility.py` checks publication/event-date separation,
metadata, stable identity, citations, and explicit extraction diagnostics.
`test_drr_persistence.py` exercises import → save → reopen → structured episode
export, plus duplicate imports, cancellation, stale sessions, write races, and
paired rollback. Dependencies must first be installed from `requirements.txt`.

Run all browser-free frontend checks with `npm run test:unit`. The DRR component
and handler checks cover diagnostic display, read-only metadata, pending-edit
flushing, and document changes during a save. They do not verify pixels or
website behavior.

Unified JSON projects have fixture-only coverage in `test_project_document.py` and
`test_project_api.py`: lossless conversion, version/identity validation, unknown
metadata, missing-link notices, save/reopen, Save As, next-start configuration,
cancellation, failed writes, stale sessions, parser imports and recursive selection
exports with both Draft choices. All writes use temporary directories.

`tests/unit/unified-project.test.cjs` covers shared history, timer cancellation,
full-project save snapshots and lossless research-field encoding. The full-App
startup test loads both legacy and unified data, creates an item and source,
undoes across views, saves a copy and redoes an action. These checks execute the
actual App function and effects with simulated React hooks and API responses;
they do not establish actual browser rendering, focus, or native-dialog behavior.
The browser suite's fixtures have been updated for the unified project UI but
must be run separately when browser automation is authorized.
