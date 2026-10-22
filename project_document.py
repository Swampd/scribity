"""Versioned Scribity project documents. No UI, session, or schema normalization."""
import copy
import json
import os
import tempfile
import uuid


FORMAT = 'scribity-project'
VERSION = 1


def validate_project(document):
    if not isinstance(document, dict) or document.get('format') != FORMAT:
        raise ValueError('Choose a Scribity project JSON file. Use Import legacy pair for separate items/sources files.')
    if type(document.get('version')) is not int or document['version'] != VERSION:
        raise ValueError('Unsupported project format version. This Scribity supports version 1.')
    for field in ('project_id', 'name'):
        if not isinstance(document.get(field), str) or not document[field].strip():
            raise ValueError(f'Project {field} must be a nonempty string.')
    if document.get('schema_mode', 'improv') not in ('improv', 'research'):
        raise ValueError('Project schema_mode must be improv or research.')
    for field, key in (('items', 'id_item'), ('sources', 'id_source')):
        records = document.get(field)
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise ValueError(f'Project {field} must be an array of objects.')
        ids = [record.get(key) for record in records]
        if any(not isinstance(value, str) or not value.strip() for value in ids) or len(set(ids)) != len(ids):
            raise ValueError(f'Project {field} require unique, nonempty {key} values. No records were changed.')
    return document


def new_project(name, items, sources, mode='improv'):
    return validate_project(copy.deepcopy({
        'format': FORMAT, 'version': VERSION, 'project_id': uuid.uuid4().hex,
        'name': name, 'schema_mode': mode, 'items': items, 'sources': sources,
    }))


def load_project(path):
    with open(path, encoding='utf-8') as handle:
        return validate_project(json.load(handle))


def write_project(path, document, *, new=False):
    validate_project(document)
    path = os.path.abspath(path)
    fd, temporary = tempfile.mkstemp(prefix='.scribity-project-', suffix='.tmp', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        if new:
            # Atomic no-overwrite publication, including symlinks/racing writers.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def relationship_notices(document):
    """Describe existing structural problems without rewriting research."""
    items = {item['id_item']: item for item in document['items']}
    sources = {source['id_source'] for source in document['sources']}
    notices = []
    for identity, item in items.items():
        source = item.get('id_source')
        parent = item.get('nested_under')
        if source not in (None, '') and (not isinstance(source, str) or source not in sources):
            notices.append(f'{identity}: missing or invalid source reference {source!r}; retained unchanged.')
        if parent not in (None, '') and (not isinstance(parent, str) or parent not in items):
            notices.append(f'{identity}: missing or invalid supporting parent {parent!r}; retained unchanged.')
    finished = set()
    for identity in items:
        current, trail = identity, set()
        while isinstance(current, str) and current in items and current not in finished:
            if current in trail:
                notices.append(f'Support cycle involving {current}; retained unchanged.')
                break
            trail.add(current)
            current = items[current].get('nested_under')
        finished.update(trail)
    return notices
