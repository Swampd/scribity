"""
parse_drr.py — DRR Report Parser for Scribity

Parses .mdx DRR reports into structured items and sources
compatible with the research schema.

Usage:
    from parse_drr import parse_mdx_file, parse_mdx_folder
"""

import re
import os
import uuid
from typing import List, Dict, Tuple, Optional

# --- PATTERNS ---
CITE_PATTERN = re.compile(r'\[(\d+(?:,\s*\d+)*)\]')
SOURCE_LINE = re.compile(r'^(\d+)\.\s+(.+?),?\s*<(https?://[^>]+)>\s*$')
TABLE_SEPARATOR = re.compile(r'^\|\s*[-:]+\s*(\|\s*[-:]+\s*)*\|$')
JSX_LINE = re.compile(r'^\s*<\w+')

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


def _make_source(cite_num: int, raw_title: str, url: str, report_slug: str) -> dict:
    """Create a source record from a parsed source line."""
    parts = raw_title.rsplit(' - ', 1)
    src_title = parts[0].strip() if parts else raw_title
    src_publication = parts[1].strip() if len(parts) > 1 else ''
    source_id = f"src_{report_slug}_{cite_num}"

    return {
        **SOURCE_TEMPLATE,
        'id_source': source_id,
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
        'event_date_yyyy-mm-dd': report_date,
        'event_time': '',
        'latitude': '',
        'longitude': '',
        'location_name': '',
        'user_01_comments': '',
        'user_02_comments': '',
    }


def _items_from_text(text: str, section: str, subsection: str,
                     title: str, report_date: str, source_map: dict) -> list:
    """Split text at citation boundaries and create items.

    For multi-citation like [1, 2, 3], creates duplicate items linked
    via related_facts.
    """
    citations = list(CITE_PATTERN.finditer(text))
    if not citations:
        return []

    items = []
    prev_end = 0

    for match in citations:
        segment = text[prev_end:match.start()].strip()
        cite_nums = [int(n.strip()) for n in match.group(1).split(',')]
        prev_end = match.end()

        if not segment:
            continue

        if len(cite_nums) == 1:
            items.append(_make_item(segment, cite_nums[0], section, subsection,
                                    title, report_date, source_map))
        else:
            # Multi-citation: duplicate items, linked via related_facts
            group_id = f"grp_{uuid.uuid4().hex[:8]}"
            for cn in cite_nums:
                item = _make_item(segment, cn, section, subsection,
                                  title, report_date, source_map)
                item['related_facts'] = [group_id]
                item['relates_to_other_facts'] = True
                items.append(item)

    return items


def _process_table(table_lead_in: str, table_header: str,
                   table_separator: str, table_rows: list,
                   section: str, subsection: str,
                   title: str, report_date: str, source_map: dict) -> list:
    """Process a markdown table into items.

    - If all rows share the same citations: one item with full table.
    - Otherwise: one item per row with lead-in + headers + that row.
    - Multi-citation rows produce duplicate items linked via related_facts.
    """
    if not table_rows:
        return []

    items = []
    clean_lead = CITE_PATTERN.sub('', table_lead_in).strip() if table_lead_in else ''

    # Collect citations per row (merged across all columns)
    row_cite_sets = []
    for row in table_rows:
        cells = row.split('|')
        row_cites = set()
        for cell in cells:
            for m in CITE_PATTERN.finditer(cell):
                for n in m.group(1).split(','):
                    row_cites.add(int(n.strip()))
        row_cite_sets.append(row_cites)

    # Check if uniform citations across all rows
    cited_rows = [rc for rc in row_cite_sets if rc]
    all_uniform = (len(cited_rows) > 0 and
                   all(rc == cited_rows[0] for rc in cited_rows))

    if all_uniform and cited_rows:
        # Uniform: one item with full table
        full_table_lines = [table_header, table_separator] + table_rows
        clean_table = CITE_PATTERN.sub('', '\n'.join(full_table_lines)).strip()
        quote = f"{clean_lead}\n{clean_table}" if clean_lead else clean_table
        cite_list = list(cited_rows[0])

        if len(cite_list) == 1:
            items.append(_make_item(quote, cite_list[0], section, subsection,
                                    title, report_date, source_map))
        else:
            group_id = f"grp_{uuid.uuid4().hex[:8]}"
            for cn in cite_list:
                item = _make_item(quote, cn, section, subsection,
                                  title, report_date, source_map)
                item['related_facts'] = [group_id]
                item['relates_to_other_facts'] = True
                items.append(item)
    else:
        # Different citations per row: one item per row
        clean_header = CITE_PATTERN.sub('', table_header).strip()
        for i, row in enumerate(table_rows):
            row_cites = row_cite_sets[i]
            if not row_cites:
                continue  # Skip uncited rows

            clean_row = CITE_PATTERN.sub('', row).strip()
            parts = [p for p in [clean_lead, clean_header, table_separator, clean_row] if p]
            quote = '\n'.join(parts)
            cite_list = list(row_cites)

            if len(cite_list) == 1:
                items.append(_make_item(quote, cite_list[0], section, subsection,
                                        title, report_date, source_map))
            else:
                group_id = f"grp_{uuid.uuid4().hex[:8]}"
                for cn in cite_list:
                    item = _make_item(quote, cn, section, subsection,
                                      title, report_date, source_map)
                    item['related_facts'] = [group_id]
                    item['relates_to_other_facts'] = True
                    items.append(item)

    return items


def parse_mdx_file(filepath: str) -> dict:
    """Parse a single .mdx DRR report file.

    Returns:
        {
            'items': [...],
            'sources': [...],
            'title': str,
            'report_date': str,
            'filepath': str,
            'stats': { 'items': int, 'sources': int, 'sections': int }
        }
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')

    basename = os.path.splitext(os.path.basename(filepath))[0]
    report_slug = re.sub(r'[^a-zA-Z0-9]', '_', basename)[:50]

    # --- Phase 1: Frontmatter ---
    report_date = ''
    frontmatter_end = 0
    if lines and lines[0].strip() == '---':
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                frontmatter_end = i + 1
                break
            m = re.match(r'publishedOn:\s*"(.+?)"', lines[i].strip())
            if m:
                report_date = m.group(1)

    # --- Phase 2: Title ---
    title = ''
    for i in range(frontmatter_end, len(lines)):
        s = lines[i].strip()
        if s.startswith('# ') and not s.startswith('## '):
            title = s[2:].strip()
            break

    # --- Phase 3: Sources section (parse from end) ---
    sources_start = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == '## Sources':
            sources_start = i
            break

    source_map = {}
    if sources_start is not None:
        for i in range(sources_start + 1, len(lines)):
            m = SOURCE_LINE.match(lines[i].strip())
            if m:
                cn = int(m.group(1))
                source_map[cn] = _make_source(cn, m.group(2).strip(),
                                              m.group(3).strip(), report_slug)

    # --- Phase 4: Body parsing ---
    # Find first ## heading (skip everything before it: summary + JSX)
    body_start = None
    body_end = sources_start if sources_start else len(lines)
    for i in range(frontmatter_end, len(lines)):
        s = lines[i].strip()
        if s.startswith('## ') and s != '## Sources':
            body_start = i
            break

    empty_result = {
        'items': [], 'sources': list(source_map.values()),
        'title': title, 'report_date': report_date, 'filepath': filepath,
        'stats': {'items': 0, 'sources': len(source_map), 'sections': 0}
    }
    if body_start is None:
        return empty_result

    # State
    all_items = []
    current_section = ''
    current_subsection = ''
    section_count = 0
    para_lines = []
    table_lead_in = ''

    # Table state
    in_table = False
    t_header = ''
    t_sep = ''
    t_rows = []

    def flush_para():
        nonlocal para_lines, table_lead_in
        if not para_lines:
            return
        text = ' '.join(para_lines).strip()
        para_lines = []
        if not text:
            return
        # Store as potential table lead-in (stripped of cites for context)
        table_lead_in = text
        # Create items from citation-delimited segments
        all_items.extend(_items_from_text(text, current_section, current_subsection,
                                          title, report_date, source_map))

    def flush_table():
        nonlocal in_table, t_header, t_sep, t_rows
        if t_rows:
            all_items.extend(_process_table(
                table_lead_in, t_header, t_sep, t_rows,
                current_section, current_subsection,
                title, report_date, source_map
            ))
        in_table = False
        t_header = ''
        t_sep = ''
        t_rows = []

    i = body_start
    while i < body_end:
        line = lines[i]
        stripped = line.strip()

        # Empty line: flush current accumulator
        if not stripped:
            if in_table:
                flush_table()
            else:
                flush_para()
            i += 1
            continue

        # Horizontal rule
        if stripped == '---':
            flush_para()
            if in_table:
                flush_table()
            i += 1
            continue

        # JSX components (skip)
        if JSX_LINE.match(stripped) and ('/' in stripped or '</' in stripped):
            flush_para()
            i += 1
            continue

        # Section headers
        if stripped.startswith('### '):
            flush_para()
            if in_table:
                flush_table()
            current_subsection = stripped[4:].strip()
            i += 1
            continue

        if stripped.startswith('## '):
            flush_para()
            if in_table:
                flush_table()
            current_section = stripped[3:].strip()
            current_subsection = ''
            section_count += 1
            i += 1
            continue

        # Table handling
        if stripped.startswith('|'):
            if not in_table:
                flush_para()
                in_table = True
                t_header = stripped
                # Check next line for separator
                if i + 1 < body_end and TABLE_SEPARATOR.match(lines[i + 1].strip()):
                    t_sep = lines[i + 1].strip()
                    i += 2
                    continue
                i += 1
                continue
            elif TABLE_SEPARATOR.match(stripped):
                t_sep = stripped
                i += 1
                continue
            else:
                t_rows.append(stripped)
                i += 1
                continue

        # Blockquote
        if stripped.startswith('> '):
            flush_para()
            if in_table:
                flush_table()
            bq_text = stripped[2:].strip()
            all_items.extend(_items_from_text(bq_text, current_section, current_subsection,
                                              title, report_date, source_map))
            i += 1
            continue

        # Regular paragraph line
        if in_table:
            flush_table()
        para_lines.append(stripped)
        i += 1

    # Final flush
    flush_para()
    if in_table:
        flush_table()

    return {
        'items': all_items,
        'sources': list(source_map.values()),
        'title': title,
        'report_date': report_date,
        'filepath': filepath,
        'stats': {
            'items': len(all_items),
            'sources': len(source_map),
            'sections': section_count,
        }
    }


def parse_mdx_folder(folderpath: str) -> dict:
    """Parse all .mdx files in a folder.

    Returns combined results with per-file stats.
    """
    all_items = []
    all_sources = []
    file_results = []

    mdx_files = sorted([
        f for f in os.listdir(folderpath)
        if f.lower().endswith('.mdx')
    ])

    for filename in mdx_files:
        filepath = os.path.join(folderpath, filename)
        result = parse_mdx_file(filepath)
        all_items.extend(result['items'])
        all_sources.extend(result['sources'])
        file_results.append({
            'filename': filename,
            'title': result['title'],
            'stats': result['stats']
        })

    return {
        'items': all_items,
        'sources': all_sources,
        'files': file_results,
        'stats': {
            'total_items': len(all_items),
            'total_sources': len(all_sources),
            'total_files': len(mdx_files),
        }
    }


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
