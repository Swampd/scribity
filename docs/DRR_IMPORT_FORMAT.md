# Research report import format

Scribity reads the same metadata-bearing MDX file that a website can render.
This page documents the **Scribity implementation**. Website and pipeline
compatibility still need to be checked by their maintainers using the same
sample report. No archive migration is performed by the importer.

## Example and expected results

- [Synthetic report](../tests/fixtures/drr/metadata-history.mdx)
- [Expected extracted results](../tests/fixtures/drr/metadata-history.expected.json)

These are small test files, not research evidence. They pin the new fields to
`drrSchemaVersion: 1` and `reportId`. The sample publication date is in 2026;
its passages mention 1901 and 1976. All extracted event-date fields remain
empty. A passage citing two sources produces two linked items, so three items
represent two passages. Two source numbers sharing a URL remain separate
bibliography records.

## Metadata

Use YAML frontmatter bounded by `---` lines:

```yaml
---
drrSchemaVersion: 1
reportId: permanent-report-identifier
title: Report title
summary: Brief description
publishedOn: '2026-10-16'
updatedOn: '2026-10-17'
author: Example Author
---
```

- Keep `reportId` unchanged when renaming or revising the report. Prefer a UUID
  or a unique, permanent string. Never reuse it for a different report.
- `drrSchemaVersion` is the integer `1`. Unsupported versions block import.
- `publishedOn` is the actual publication date, or `null` for an unpublished
  report. Version 1 requires the field. Optional `updatedOn` is a revision date
  or `null`. Non-null dates must be valid `YYYY-MM-DD` strings.
- Historical scope can be separate metadata. It is never a publication date.
  The importer does not infer item event dates from prose, report dates, or
  source dates. Those fields stay empty until explicitly edited in Scribity.
- Unknown metadata, including nested objects and arrays, is retained. Parsed
  metadata and raw frontmatter both survive saves and structured project exports.
  Only include metadata appropriate for the document's intended audience.
- YAML is parsed with a restricted safe loader. Duplicate/non-string keys,
  aliases, merge keys, executable/custom tags, non-JSON values, and invalid YAML
  block import. Unquoted dates remain strings. Scalar booleans/numbers use
  PyYAML's safe YAML rules; quote values intended as literal strings.
- Unversioned reports remain readable with a visible migration warning. Without
  `reportId`, legacy identity is derived from the relative filename, so renaming
  changes it. Existing imported data is never retroactively rewritten.

## Research body and sources

Use one `#` report title, `##` sections, and optional `###` subsections. Put
research below a section heading. Cited opening prose is still extracted under
Introduction with a warning rather than discarded.

Each passage should end in `[1]` or a grouped marker such as `[1, 2]`, with
punctuation before the citation. Sources belong in one final `## Sources`
section, one entry per line:

```markdown
## Findings

A complete supported passage. [1, 2]

## Sources

1. First source <https://example.com/one>
2. Second source <https://example.com/two>
```

Citations divide passages. Multi-source passages retain Scribity's existing
linked-duplicate model: one item per source, with a shared `grp_*` identifier.
Within an unchanged report, item/source/group identities survive a rename.
Item identities may change when passages are edited or reordered; this importer
is not a revision-merging system.

Plain cited lists, blockquotes, and Markdown tables are extracted. Tables need
headers and separator rows, with citations on every data row; each row becomes
its own passage. A citation in one row never supplies a source for another.
Header citations are ambiguous and block import. Complex/nested formatting may
need to be expressed as ordinary cited prose.

Missing or duplicate source numbers, malformed bibliography lines, unsupported
citation syntax, uncited passages, and text after the last citation produce
errors with filenames, line numbers, and the original text. Preview counts are
**extracted items**, not proof of full coverage.

HTML, JSX (including chart and callout components), MDX expressions, and code
fences are not executed or interpreted. They are explicitly flagged and block
saving; there is currently no “ignore errors” override. Preserve the original
material when repairing a report. Unique evidence must be available in cited
prose. Component extraction remains a separate integration task; a website
rendering a component does not prove Scribity extracted its evidence.

## Import, persistence, and episode projects

Open **Parser**, select a report or a folder, and review the messages and
**Report metadata** panels. Folder selection reads only directly contained
`.mdx` files. Duplicate report IDs in one folder block the combined import.

When the report has no blocking errors, use **Save to New File** or **Append to
Current**. Pending edits finish saving before an import is written. A document
switch during that wait cancels the import operation. Both files are written
with the existing paired-write protections. New imports use no-overwrite
publication; a failed second write removes only the first newly created file.

An existing report ID prevents another append, including revised editions.
Save a revision to a separate project for comparison; append does not merge,
replace, or deduplicate user-edited research. Projects imported before report
provenance existed cannot be recognized by report ID; legacy source-ID
collision checks still apply.

Every imported item and source carries an optional `report_provenance` object:
report ID and identity kind, format version, original title, complete metadata,
raw frontmatter, content SHA-256, citation number, import readiness, and
import-time diagnostics. Items also retain the original passage line number.
The metadata panel is read-only so nested metadata cannot be flattened by a
text input. Existing editing, Save As, reload, and Create project from Draft
preserve the object. Empty Draft project creation resets only Draft membership.

“Export” in this compatibility check means the structured items/sources project
pair. Rendered Markdown/script output is unchanged and is not a lossless MDX
round-trip exporter. The authoritative MDX file is never rewritten.

## Validation for developers

Install `requirements.txt` (now including pinned PyYAML), then restart Scribity.
To check a report without opening or saving a project:

```sh
.venv/bin/python parse_drr.py tests/fixtures/drr/metadata-history.mdx
```

The CLI exits `0` for an importable report and `2` for blocking diagnostics.
Code callers can use `parse_mdx_file()` or `parse_mdx_folder()` and inspect
`can_import`, `diagnostics`, `report` (single file), and `files[].report` (folder).
Always check readiness before consuming the partial extracted results.

Tests run entirely against synthetic reports and temporary JSON pairs:

```sh
.venv/bin/python -m unittest discover
npm run test:unit
```

The persistence check imports, saves, reloads, edits notes, and creates an episode
project. Tests also cover malformed input, source associations, stable IDs,
repeat imports, cancellation, stale document sessions, write races, and rollback.
Node checks execute the actual dashboard handlers/components without a browser.
They do not establish visual layout or website rendering compatibility.
