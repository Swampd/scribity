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
