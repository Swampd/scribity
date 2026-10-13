"""Lossless selection copies, with explicit handling of project-local links."""
import copy
import math


AUDIT_FIELD = '_scribity_external_references'


def build_project(items, sources, scope='draft', selected_ids=None, empty_draft=True):
    """Build a copy; never mutate the inputs or follow non-support references."""
    if scope not in ('draft', 'checked', 'filtered'):
        raise ValueError('Choose Draft, checked items, or filtered results.')
    if not isinstance(empty_draft, bool):
        raise ValueError('The Draft option must be a boolean.')
    by_id = {}
    for item in items:
        identity = item.get('id_item')
        if not isinstance(identity, str) or not identity.strip() or identity in by_id:
            raise ValueError('Items need unique, nonempty string IDs before extraction.')
        by_id[identity] = item
    if scope == 'draft':
        def in_draft(item):
            try:
                value = float(item.get('id_script') or 0)
                return math.isfinite(value) and value > 0 and not item.get('nested_under')
            except (TypeError, ValueError):
                return False
        selected = {key for key, item in by_id.items() if in_draft(item)}
    else:
        if not isinstance(selected_ids, list) or any(not isinstance(x, str) for x in selected_ids):
            raise ValueError('Selection must be a list of item IDs.')
        selected = set(selected_ids)
        if selected - by_id.keys():
            raise ValueError('Some selected items no longer exist. Refresh the preview.')

    children = {}
    for identity, item in by_id.items():
        parent = item.get('nested_under')
        if parent and not isinstance(parent, str):
            raise ValueError(f'{identity}: nested_under must be a single item ID.')
        if parent:
            children.setdefault(parent, []).append(identity)
    included = set(selected)
    pending = list(selected)
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in included:
                included.add(child)
                pending.append(child)

    warnings, errors = [], []
    if not selected:
        errors.append('This scope has no selected items.')
    # Iterative traversal: safe for deep support chains and malformed cycles.
    finished = set()
    for identity in included:
        trail, positions = [], set()
        current = identity
        while current in included and current not in finished:
            if current in positions:
                errors.append('Support cycle: ' + ' → '.join(trail[trail.index(current):] + [current]))
                break
            trail.append(current)
            positions.add(current)
            current = by_id[current].get('nested_under') or ''
        finished.update(trail)

    result = []
    for identity, original in by_id.items():
        if identity not in included:
            continue
        item = copy.deepcopy(original)
        if empty_draft:
            item['id_script'] = 0

        def archive(field, value, reason):
            existing = item.setdefault(AUDIT_FIELD, [])
            if not isinstance(existing, list):
                errors.append(f'{identity}: {AUDIT_FIELD} is not a list; cannot retain link provenance safely.')
                return False
            existing.append({'field': field, 'value': copy.deepcopy(value), 'reason': reason})
            warnings.append(f'{identity}: {field} {value!r} — {reason}; original value retained in {AUDIT_FIELD}.')
            return True

        parent = item.get('nested_under')
        if parent and parent not in included:
            reason = 'parent outside selection' if parent in by_id else 'parent missing from original project'
            if archive('nested_under', parent, reason):
                item['nested_under'] = ''

        # related_facts also carries parser-generated grp_* labels, not item IDs.
        # These labels remain intact even if other group members are not selected.
        for field in ('related_facts', 'supports', 'contradicts'):
            value = item.get(field)
            if not value:
                continue
            if not isinstance(value, (str, list)) or (isinstance(value, list) and any(not isinstance(v, str) for v in value)):
                errors.append(f'{identity}: unsupported {field} shape; resolve it before extraction.')
                continue
            values = value if isinstance(value, list) else [value]
            retained = []
            for target in values:
                if target in included or (field == 'related_facts' and target.startswith('grp_') and target not in by_id):
                    retained.append(target)
                elif not archive(field, target, 'reference outside selection' if target in by_id else 'unresolved reference'):
                    retained.append(target)
            item[field] = retained if isinstance(value, list) else (retained[0] if retained else '')
        result.append(item)

    referenced = set()
    for item in result:
        source_id = item.get('id_source')
        if source_id:
            if not isinstance(source_id, str):
                errors.append(f"{item['id_item']}: id_source must be a single source ID.")
            else:
                referenced.add(source_id)
    source_by_id = {}
    for source in sources:
        identity = source.get('id_source')
        if not isinstance(identity, str) or identity not in referenced:
            continue
        if identity in source_by_id:
            if source != source_by_id[identity]:
                errors.append(f'Conflicting source records share ID {identity}.')
            else:
                warnings.append(f'Duplicate source {identity} will be included once.')
        else:
            source_by_id[identity] = copy.deepcopy(source)
    for identity in sorted(referenced - source_by_id.keys()):
        errors.append(f'Missing source record: {identity}. Restore it before extracting this selection.')
    return {
        'items': result, 'sources': list(source_by_id.values()),
        'counts': {'selected': len(selected), 'supporting': len(included - selected),
                   'total': len(result), 'sources': len(source_by_id)},
        'warnings': warnings, 'errors': errors,
    }
