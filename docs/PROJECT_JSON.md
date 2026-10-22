# Unified project JSON, version 1

A project is one ordinary UTF-8 JSON object:

```json
{
  "format": "scribity-project",
  "version": 1,
  "project_id": "stable-unique-project-id",
  "name": "Rules of Improv",
  "schema_mode": "improv",
  "items": [],
  "sources": []
}
```

`format`, `version`, `project_id`, `name`, `items`, and `sources` are required.
`schema_mode` is `improv` or `research` (defaults to `improv` if absent). Items
require unique, nonblank string `id_item` values; sources require unique,
nonblank string `id_source` values. Empty lists are valid. Source URLs are not
required. Other project and record properties are preserved, including nested
metadata. Unsupported versions and ambiguous IDs are rejected without repair.

## Open, convert, save

- **Open Project** loads both lists. The next launch remembers this one path.
- **Convert loaded pair** reads the current pair after pending edits finish,
  writes a new project, and opens it. It does not alter the original files as
  part of conversion. Edits made before conversion are saved to their original
  pair by the existing editing workflow.
- **+ New → Import legacy items/sources pair…** selects another existing pair
  and writes a new project. Records are copied without normalization or ID changes.
- **+ New → New Project** creates an empty Book/improv or Show/research project.
- Autosave writes one project snapshot with both lists. **Save As…** writes and
  opens a new filename, preserving project identity and session undo history.
- Selection extraction creates a new project identity and retains project-level
  metadata, selected records, and recursively included support. The existing
  extraction rules for dangling references, missing sources and cycles apply.
- Parser **Save to New File** creates `scribity_project.json` beside the selected
  report/folder, using a numbered filename if needed. Append updates both lists
  in the active project and is one undoable action. Parser readiness rules remain.

Creation, conversion, extraction and Save As never overwrite existing files or
the active originals. They require an existing destination directory. Native
picker cancellation leaves the active document intact. When native dialogs are
unavailable, controls ask for absolute paths. Existing pairs can still be loaded
by the compatibility API; separate-file mutations are blocked while a unified
project is active.

## Manual editing and relationships

Finish edits, wait for the saved status, then close Scribity before editing its
JSON externally. Reopen the project afterward. Ordinary autosaves do not yet
detect external file edits: that remains a deferred reliability task.

Keep record IDs stable when editing. Blank/missing item `id_source` means
intentionally unlinked. A nonblank source ID without a corresponding source,
a missing supporting parent, or a support cycle is reported in the app without
rewriting the records. This preserves imperfect research while making the
problem visible. Extraction still refuses relationships it cannot safely copy.

## Scope and boundaries

`project_document.py` handles encoding, validation and atomic file publication;
`project_api.py` handles project sessions and lifecycle operations. The UI uses
the same record editing interface, one save queue and one action history for a
unified project. SQLite storage is not implemented.

History remains session-only (30 actions). Automatic orphan repair, autosave
retry/recovery, external-change conflict handling, and broader legacy switch
repairs remain deferred. A new project's activation persists configuration
before changing the active session. If that configuration write fails after a
new file was saved, the error identifies its path; the previous session stays
active and the saved file can be opened later.

New-file publication uses a no-overwrite hard link to a staged file, as existing
selection extraction does. Choose a local filesystem supporting hard links.
