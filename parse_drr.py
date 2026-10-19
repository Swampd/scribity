"""
parse_drr.py — DRR Report Parser for Scribity

Parses .mdx DRR reports into structured items and sources
compatible with the research schema.

Usage:
    from parse_drr import parse_mdx_file, parse_mdx_folder
"""

import hashlib
import json
from copy import deepcopy
from datetime import date
from urllib.parse import urlsplit
import os
import posixpath
import re
import unicodedata
import uuid
from typing import Optional

import yaml

# --- PATTERNS ---
CITE_PATTERN = re.compile(r'\[(\d+(?:,\s*\d+)*)\]')
SOURCE_LINE = re.compile(r'^(\d+)\.\s+(.+?),?\s*<(https?://[^>]+)>\s*$')
TABLE_SEPARATOR = re.compile(r'^\|\s*[-:]+\s*(\|\s*[-:]+\s*)*\|$')

# --- SOURCE TEMPLATE ---
SOURCE_TEMPLATE = {
    "id_source": "", "short_cite": "", "author": "", "title": "",
    "publication": "", "additional_source_details": "",
    "date_published": "", "date_accessed": "", "url": "", "archive_url": "",
    "page": "", "timestamp": "",
    "source_within_source_short_cite": "", "source_within_source_full_link": "",
    "related_reading": "", "needs_verification": False, "relevance_tags": [],
    "script_tags": "", "script_notes": "", "edit_tags": "",
    "user_01_comments": "", "user_02_comments": "", "to_do": ""
}


def _normalize_report_identity(report_identity: str) -> str:
    """Normalize a relative report path consistently across operating systems."""
    normalized = unicodedata.normalize('NFC', os.fspath(report_identity))
    return posixpath.normpath(normalized.replace('\\', '/'))


def _report_identity_digest(report_identity: str, cite_num: int) -> str:
    """Return a stable collision-resistant digest for one report citation."""
    identity = _normalize_report_identity(report_identity)
    digest_input = f"{identity}\0{cite_num}".encode('utf-8')
    return hashlib.sha256(digest_input).hexdigest()[:16]


def _source_id(cite_num: int, report_identity: str) -> str:
    """Build a readable ID whose uniqueness comes from the full report identity."""
    identity = _normalize_report_identity(report_identity)
    basename = posixpath.splitext(posixpath.basename(identity))[0]
    report_slug = re.sub(r'[^a-zA-Z0-9]', '_', basename)[:36] or 'report'
    digest = _report_identity_digest(identity, cite_num)
    return f"src_{report_slug}_{cite_num}_{digest}"


def _make_source(cite_num: int, raw_title: str, url: str,
                 report_identity: str) -> dict:
    """Create a source record from a parsed source line."""
    parts = raw_title.rsplit(' - ', 1)
    src_title = parts[0].strip() if parts else raw_title
    src_publication = parts[1].strip() if len(parts) > 1 else ''

    return {
        **SOURCE_TEMPLATE,
        'id_source': _source_id(cite_num, report_identity),
        'short_cite': raw_title[:80],
        'title': src_title,
        'publication': src_publication,
        'url': url,
    }


def _make_item(text: str, cite_num: int, section: str, subsection: str,
               title: str, report_date: str, source_map: dict) -> dict:
    """Create an item record from parsed text and a citation number."""
    source = source_map.get(cite_num, {})
    return {
        'id_item': str(uuid.uuid4()),
        'id_source': source.get('id_source', ''),
        'id_script': 0,
        'id_subpart': [0] if subsection else [],
        'category_part_name': [section] if section else [],
        'category_part_number': [],
        'subpart_name': [subsection] if subsection else [],
        'subpart_number': [],
        'quote_original': text,
        'quote_translation': '',
        'quoted_speaker_name': '',
        'language': '',
        'contains_example': False,
        'contains_only_example': False,
        'example': '', 'example_02': '', 'example_03': '',
        'example_note': '', 'example_02_note': '', 'example_03_note': '',
        'relates_to_other_facts': False,
        'controversial_fact': False,
        'related_facts': [],
        'supports': '',
        'contradicts': '',
        'short_cite': source.get('short_cite', ''),
        'url': source.get('url', ''),
        'script_part': title,
        'edit_tags': '',
        'relevance_tags': [],
        'needs_verification': False,
        'script_notes': '',
        'script_tags': '',
        'audio_tags': '',
        'id_extra_01': '',
        'id_extra_02': '',
        'event_date_yyyy-mm-dd': '',
        'event_time': '',
        'latitude': '',
        'longitude': '',
        'location_name': '',
        'user_01_comments': '',
        'user_02_comments': '',
    }


class MetadataLoader(yaml.SafeLoader):
    """Safe YAML with string keys, no duplicate keys, aliases or merge keys."""

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, str) or key == '<<' or key in result:
                raise ValueError('Metadata keys must be unique strings; YAML merges are unsupported.')
            result[key] = self.construct_object(value_node, deep=True)
        return result


# Keep unquoted ISO dates as strings instead of Python date objects. Other safe
# scalar types remain available; the raw frontmatter is also retained verbatim.
MetadataLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in entries
          if tag != 'tag:yaml.org,2002:timestamp']
    for key, entries in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def parse_mdx_file(filepath: str, report_identity: Optional[str] = None) -> dict:
    """Extract research without executing MDX; errors make the preview unsavable.

    Report metadata travels on every item/source so subset projects remain
    self-contained. Publication dates never supply historical event dates.
    """
    with open(filepath, 'r', encoding='utf-8-sig') as handle:
        raw = handle.read()
    lines = raw.splitlines()
    legacy_identity = _normalize_report_identity(report_identity or os.path.basename(filepath))
    diagnostics, collisions = [], []

    def diagnose(code, message, line=1, excerpt='', severity='error'):
        diagnostics.append(dict(code=code, severity=severity, message=message,
                                line=line, excerpt=excerpt, filename=os.path.basename(filepath)))

    metadata, frontmatter, start = {}, '', 0
    if lines and lines[0].strip() == '---':
        end = next((n for n in range(1, len(lines)) if lines[n].strip() == '---'), None)
        if end is None:
            diagnose('invalid_frontmatter', 'Frontmatter has no closing --- delimiter.', 1, raw)
            start = len(lines)
        else:
            frontmatter = '\n'.join(lines[1:end])
            start = end + 1
            try:
                if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(frontmatter)):
                    raise ValueError('YAML aliases are unsupported; write the values explicitly.')
                metadata = yaml.load(frontmatter, Loader=MetadataLoader)
                if not isinstance(metadata, dict):
                    raise ValueError('Frontmatter must be a mapping of named fields.')
                json.dumps(metadata, allow_nan=False)
            except (yaml.YAMLError, ValueError, TypeError, RecursionError) as error:
                metadata = {}
                diagnose('invalid_frontmatter', f'Cannot safely read metadata: {error}', 1, frontmatter)
    else:
        diagnose('missing_frontmatter', 'Legacy report has no YAML frontmatter.', severity='warning')

    version = metadata.get('drrSchemaVersion')
    report_id = metadata.get('reportId')
    if 'drrSchemaVersion' not in metadata:
        diagnose('legacy_report', 'Unversioned report: add drrSchemaVersion: 1 and a permanent reportId. '
                 'Without reportId, renaming changes identity.', severity='warning')
    elif type(version) is not int or version != 1:
        diagnose('unsupported_version', 'Supported drrSchemaVersion is the integer 1.', 1, frontmatter)
    if report_id is not None and (not isinstance(report_id, str) or not report_id.strip()):
        diagnose('missing_report_id', 'reportId must be a nonempty permanent string.', 1, frontmatter)
        report_id = None
    if version is not None and not report_id:
        diagnose('missing_report_id', 'Versioned reports require a permanent reportId.', 1, frontmatter)
    identity = report_id or legacy_identity
    for field in ('publishedOn', 'updatedOn'):
        value = metadata.get(field)
        if value is not None:
            try:
                if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                    raise ValueError()
                date.fromisoformat(value)
            except ValueError:
                diagnose('invalid_publication_date', f'{field} must be YYYY-MM-DD or null; it is not an event year.',
                         1, frontmatter)
    if version == 1 and 'publishedOn' not in metadata:
        diagnose('missing_publication_date', 'Include publishedOn with an actual date or null for an unpublished report.',
                 1, frontmatter)

    title = next((line.strip()[2:].strip() for line in lines[start:] if line.strip().startswith('# ')),
                 metadata.get('title') if isinstance(metadata.get('title'), str) else '')
    if not title:
        diagnose('missing_title', 'Add a # Report title heading or title metadata.')
    report = dict(report_id=identity, identity_kind='explicit' if report_id else 'legacy_path',
                  schema_version=version, title=title, metadata=metadata,
                  content_sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                  raw_frontmatter=frontmatter)

    source_headings = [n for n in range(start, len(lines)) if lines[n].strip() == '## Sources']
    body_end = source_headings[0] if source_headings else len(lines)
    if len(source_headings) != 1:
        diagnose('sources_section', 'Use exactly one final ## Sources section.')
    source_map = {}
    if source_headings:
        for n in range(body_end + 1, len(lines)):
            text = lines[n].strip()
            if not text:
                continue
            match = SOURCE_LINE.fullmatch(text)
            if not match:
                diagnose('malformed_source', 'Use one entry per line: 1. Source title <https://example.com/document>.', n + 1, lines[n])
                continue
            cn = int(match[1])
            url = match[3]
            if cn < 1 or re.search(r'[\s<>\[\]]', url) or not urlsplit(url).hostname:
                diagnose('malformed_source', 'Use a positive source number and a direct HTTP(S) URL.', n + 1, lines[n])
                continue
            source = _make_source(cn, match[2].strip(), url, identity)
            if cn in source_map:
                diagnose('duplicate_source', f'Citation {cn} has more than one bibliography entry.', n + 1, lines[n])
                collisions.append(dict(kind='source_id_collision', id_source=source['id_source'],
                                       reports=[legacy_identity], message=f'Citation {cn} is defined more than once.'))
                continue
            source['report_provenance'] = {**deepcopy(report), 'citation_number': cn}
            source_map[cn] = source

    items, section, subsection, sections = [], '', '', set()
    occurrence = 0

    def add_passage(text, numbers, line):
        nonlocal occurrence
        occurrence += 1
        key = f'{identity}\0{section}\0{subsection}\0{occurrence}\0{text}'
        group_id = 'grp_' + hashlib.sha256(key.encode()).hexdigest()[:24]
        for cn in dict.fromkeys(numbers):
            if cn not in source_map:
                diagnose('missing_source', f'Citation [{cn}] has no bibliography entry.', line, text + f' [{cn}]')
            item = _make_item(text, cn, section or 'Introduction', subsection, title, '', source_map)
            item['id_item'] = str(uuid.uuid5(uuid.NAMESPACE_URL, key + f'\0{cn}'))
            item['report_provenance'] = {**deepcopy(report), 'citation_number': cn, 'line': line}
            if len(set(numbers)) > 1:
                item['related_facts'] = [group_id]
                item['relates_to_other_facts'] = True
            items.append(item)

    def extract(text, line, table=False):
        if not section:
            diagnose('opening_content', 'Opening content was extracted under Introduction; move it under a ## heading.',
                     line, text, 'warning')
        # A conservative boundary: these structures need review, not execution or
        # guesses about which data/props constitute evidence.
        if (re.search(r'<(?!https?://)(?:/?[A-Za-z]|!)', text) or
                re.search(r'(^|\n)\s*(?:```|~~~|import\s|export\s)', text) or
                re.search(r'[{}]', text)):
            diagnose('unsupported_structure', 'MDX/HTML, expressions and code blocks are not extracted. '
                     'Keep this original block and provide its evidence in cited prose.', line, text)
            return
        matches = list(CITE_PATTERN.finditer(text))
        brackets = re.findall(r'\[[^\]\n]*\]', text)
        if any(not CITE_PATTERN.fullmatch(value) for value in brackets) or re.search(r'\]\s*\[', text):
            diagnose('unsupported_citation', 'Use grouped numeric citations such as [1, 2]; review this entire passage.', line, text)
            return
        if not matches:
            diagnose('uncited_text', 'This passage has no supported citation and was not extracted.', line, text)
            return
        if table:
            numbers = [int(n.strip()) for match in matches for n in match[1].split(',')]
            add_passage(CITE_PATTERN.sub('', text).strip(), numbers, line)
            return
        prev = 0
        for match in matches:
            segment = text[prev:match.start()].strip()
            if segment:
                add_passage(segment, [int(n.strip()) for n in match[1].split(',')], line)
            else:
                diagnose('empty_citation', 'Citation has no preceding passage.', line, text)
            prev = match.end()
        if text[prev:].strip():
            diagnose('trailing_text', 'Text after the final citation was not extracted; put punctuation and evidence before the citation.', line, text)

    paragraph, paragraph_line = [], start + 1

    def flush():
        if paragraph:
            extract('\n'.join(paragraph), paragraph_line)
            paragraph.clear()

    n = start
    saw_title = False
    while n < body_end:
        text = lines[n].strip()
        if not text or text == '---':
            flush()
            n += 1
            continue
        if text.startswith(('```', '~~~')):
            flush()
            fence, first = text[:3], n
            n += 1
            while n < body_end and not lines[n].strip().startswith(fence):
                n += 1
            n = min(n + 1, body_end)
            diagnose('unsupported_structure', 'Code fence not extracted; retain evidence in cited prose.', first + 1, '\n'.join(lines[first:n]))
            continue
        heading = re.match(r'^(#+)\s+(.*)$', text)
        if heading:
            flush()
            level = len(heading[1])
            if level == 1:
                if saw_title or section:
                    diagnose('unsupported_heading', 'Use one # report title; use ## for sections.', n + 1, lines[n])
                saw_title = True
            elif level == 2:
                section, subsection = heading[2], ''
                sections.add(section)
            elif level == 3:
                subsection = heading[2]
            elif level > 3:
                diagnose('unsupported_heading', 'Use headings no deeper than ###.', n + 1, lines[n])
            n += 1
            continue
        if text.startswith('|'):
            flush()
            first = n
            block = []
            while n < body_end and lines[n].strip().startswith('|'):
                block.append(lines[n].strip())
                n += 1
            if len(block) < 3 or not TABLE_SEPARATOR.fullmatch(block[1]):
                diagnose('unsupported_table', 'Table must have a header, separator and individually cited data rows.', first + 1, '\n'.join(block))
            elif CITE_PATTERN.search(block[0]):
                diagnose('unsupported_table', 'Citations in a table header are ambiguous; put evidence and citations in data rows.', first + 1, '\n'.join(block))
            else:
                for offset, row in enumerate(block[2:], 2):
                    # Header citations cannot establish evidence for an uncited row.
                    if not CITE_PATTERN.search(row):
                        diagnose('uncited_text', 'Table row has no citation; citations from other rows are not inherited.', first + offset + 1, row)
                    else:
                        extract('\n'.join([block[0], block[1], row]), first + offset + 1, table=True)
            continue
        # Lists and blockquotes retain their textual markers and source links.
        if re.match(r'^(?:[-*+] |\d+\. |> )', text):
            flush()
        if not paragraph:
            paragraph_line = n + 1
        paragraph.append(lines[n])
        n += 1
    flush()
    if not items:
        diagnose('no_passages', 'No cited research passages were extracted.')
    can_import = not any(d['severity'] == 'error' for d in diagnostics) and not collisions
    for record in items + list(source_map.values()):
        record['report_provenance']['import_ready'] = can_import
        record['report_provenance']['diagnostics'] = deepcopy(diagnostics)
    return dict(items=items, sources=list(source_map.values()), title=title,
                report_date=metadata.get('publishedOn') or '', filepath=filepath,
                report=report, diagnostics=diagnostics, can_import=can_import, collisions=collisions,
                stats=dict(items=len(items), sources=len(source_map), sections=len(sections),
                           source_id_collisions=len(collisions)))


def parse_mdx_folder(folderpath: str) -> dict:
    """Parse top-level MDX files, retaining each report's metadata and diagnostics."""
    items, sources, files, diagnostics = [], [], [], []
    collisions, source_reports, report_ids = {}, {}, {}
    for filename in sorted(f for f in os.listdir(folderpath) if f.lower().endswith('.mdx')):
        result = parse_mdx_file(os.path.join(folderpath, filename), report_identity=filename)
        items.extend(result['items'])
        sources.extend(result['sources'])
        diagnostics.extend(result['diagnostics'])
        report_id = result['report']['report_id']
        if report_id in report_ids:
            diagnostics.append(dict(code='duplicate_report_id', severity='error', line=1, filename=filename,
                                    excerpt=report_id, message=f'Report identity also occurs in {report_ids[report_id]}; select only one edition.'))
        report_ids[report_id] = filename
        for collision in result['collisions']:
            collisions[collision['id_source']] = collision
        for source in result['sources']:
            sid = source['id_source']
            if sid in source_reports:
                collision = collisions.setdefault(sid, dict(kind='source_id_collision', id_source=sid,
                    reports=[source_reports[sid]], message=f'Source ID {sid} occurs in multiple reports.'))
                if filename not in collision['reports']:
                    collision['reports'].append(filename)
            else:
                source_reports[sid] = filename
        files.append(dict(filename=filename, title=result['title'], stats=result['stats'], report=result['report'],
                          diagnostics=result['diagnostics'], can_import=result['can_import']))
    if not files:
        diagnostics.append(dict(code='no_reports', severity='error', line=1, filename='', excerpt='',
                                message='No .mdx reports found directly inside this folder.'))
    return dict(items=items, sources=sources, files=files, diagnostics=diagnostics,
                can_import=not collisions and not any(d['severity'] == 'error' for d in diagnostics),
                collisions=list(collisions.values()), stats=dict(total_items=len(items), total_sources=len(sources),
                    total_files=len(files), source_id_collisions=len(collisions)))


# --- CLI for testing ---
if __name__ == '__main__':
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python parse_drr.py <file_or_folder>")
        sys.exit(1)

    target = sys.argv[1]
    if os.path.isdir(target):
        result = parse_mdx_folder(target)
        print(f"\n=== Folder Parse: {target} ===")
        print(f"Files: {result['stats']['total_files']}")
        for fr in result['files']:
            s = fr['stats']
            print(f"  {fr['filename']}: {s['items']} items, {s['sources']} sources, {s['sections']} sections")
    else:
        result = parse_mdx_file(target)
        print(f"\n=== File Parse: {target} ===")
        print(f"Title: {result['title']}")
        print(f"Date: {result['report_date']}")

    print(f"\nTotal Items: {result['stats'].get('total_items', result['stats'].get('items'))}")
    print(f"Total Sources: {result['stats'].get('total_sources', result['stats'].get('sources'))}")

    # Dump first 3 items as sample
    sample = result['items'][:3]
    print(f"\n--- Sample Items (first 3) ---")
    for it in sample:
        print(f"  [{it['short_cite'][:40]}] {it['quote_original'][:100]}...")
        print(f"    Section: {it['category_part_name']} / {it['subpart_name']}")
        print(f"    Related: {it['related_facts']}")
        print()

    for diagnostic in result["diagnostics"]:
        print(f"{diagnostic['severity'].upper()} {diagnostic['filename']}:{diagnostic['line']} {diagnostic['message']}")
    sys.exit(0 if result["can_import"] else 2)
