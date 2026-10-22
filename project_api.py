"""Unified JSON project lifecycle, separate from record editing and file encoding."""
import copy
import os
import uuid
from flask import jsonify, request
from project_document import load_project, new_project, write_project, relationship_notices


class ProjectAPI:
    def __init__(self, server):
        self.s = server
        server.app.add_url_rule('/api/project/action', 'project_action', self.action, methods=['POST'])
        server.app.add_url_rule('/api/project/save', 'project_save', self.save, methods=['POST'])
        server.app.before_request(self.guard_legacy_writes)

    def guard_legacy_writes(self):
        if self.s.PROJECT_PATH and request.endpoint in {
            'open_items_picker', 'open_sources_picker', 'switch_items_manual', 'switch_sources_manual',
            'save_items_endpoint', 'save_sources_endpoint', 'save_items_as', 'save_sources_as',
            'new_document', 'save_new_document',
        }:
            return jsonify(status='error', message='A unified project is open. Use project controls to save or switch it.'), 409

    def check_request(self, payload):
        for kind in ('items', 'sources'):
            if not self.s.document_request_is_current(kind, payload.get(kind + '_document')):
                return self.s.stale_document_response(kind)
        return None

    def response(self, document):
        state = self.s.current_document_state('items')
        filename = os.path.basename(self.s.PROJECT_PATH)
        return dict(status='success', items=document['items'], sources=document['sources'],
                    items_filename=filename, sources_filename=filename,
                    items_document=state, sources_document=state,
                    project={'path': self.s.PROJECT_PATH, 'filename': filename,
                             'project_id': document['project_id'], 'name': document['name'],
                             'schema_mode': document.get('schema_mode', 'improv')},
                    notices=relationship_notices(document))

    def activate(self, path, document):
        # Nothing becomes active unless persistence of the next-start choice succeeds.
        self.s.save_json(self.s.CONFIG_PATH, {'project_path': path})
        self.s.PROJECT_PATH = path
        self.s.PROJECT_DOCUMENT = {'token': uuid.uuid4().hex, 'revision': 0}
        self.s.ITEMS_READY = self.s.SOURCES_READY = True
        return self.response(document)

    def choose_path(self, payload, *, save, key='path', title='Open Project', filename='project.json'):
        if key in payload:
            path = payload[key]
        elif not self.s.TK_AVAILABLE:
            return None
        else:
            try:
                root = self.s.tk.Tk()
            except Exception:
                # Tk may be installed without a usable display. Let the UI ask for a path.
                return None
            try:
                root.withdraw(); root.wm_attributes('-topmost', 1)
                options = dict(title=title, filetypes=(("JSON files", "*.json"),))
                if save:
                    path = self.s.filedialog.asksaveasfilename(**options, initialfile=filename, defaultextension='.json')
                else:
                    path = self.s.filedialog.askopenfilename(**options)
            finally:
                root.destroy()
        if path == '':
            return ''
        if not isinstance(path, str) or not os.path.isabs(path):
            raise ValueError('Enter an absolute JSON file path.')
        return os.path.abspath(path)

    @staticmethod
    def path_response(path):
        return jsonify(status='gui_unavailable' if path is None else 'canceled')

    def protected_paths(self):
        return [path for path in (self.s.PROJECT_PATH, self.s.ITEMS_PATH, self.s.SOURCES_PATH) if path]

    def write_new(self, path, document, originals=()):
        if any(self.s.paths_refer_to_same_file(path, original) for original in [*self.protected_paths(), *originals]):
            raise ValueError('Choose a new filename. Original research files cannot be overwritten by conversion or Save As.')
        write_project(path, document, new=True)

    def action(self):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(status='error', message='Expected a JSON object.'), 400
        try:
            with self.s.SAVE_LOCK:
                error = self.check_request(payload)
                if error is not None:
                    return error
            operation = payload.get('operation')
            if operation not in ('open', 'new', 'convert', 'save_as'):
                raise ValueError('Unknown project action.')
            legacy_paths = []
            if operation == 'convert':
                if payload.get('use_current'):
                    if self.s.PROJECT_PATH:
                        raise ValueError('This is already a unified project. Use Save As to copy it.')
                    legacy_paths = [self.s.ITEMS_PATH, self.s.SOURCES_PATH]
                else:
                    for key, title in (('items_path', 'Import legacy pair — Items JSON'),
                                       ('sources_path', 'Import legacy pair — Sources JSON')):
                        selected = self.choose_path(payload, save=False, key=key, title=title)
                        if not selected:
                            return self.path_response(selected)
                        legacy_paths.append(selected)
                if self.s.paths_refer_to_same_file(*legacy_paths):
                    raise ValueError('Choose different items and sources files.')
            path = self.choose_path(payload, save=operation != 'open', title={
                'open': 'Open Project', 'new': 'New Project', 'convert': 'Save converted project', 'save_as': 'Save Project As'
            }[operation])
            if not path:
                return self.path_response(path)
            with self.s.SAVE_LOCK:
                error = self.check_request(payload)
                if error is not None:
                    return error
                if operation == 'open':
                    document = load_project(path)
                elif operation == 'save_as':
                    if not self.s.PROJECT_PATH:
                        raise ValueError('Convert the legacy pair to a project first.')
                    document = load_project(self.s.PROJECT_PATH)
                else:
                    items, sources = ([self.s.load_json(p) for p in legacy_paths] if legacy_paths else ([], []))
                    mode = payload.get('mode') or ('research' if any('category_part_name' in i for i in items) else 'improv')
                    document = new_project(os.path.splitext(os.path.basename(path))[0], items, sources, mode)
                if operation != 'open':
                    self.write_new(path, document, legacy_paths)
                try:
                    return jsonify(self.activate(path, document))
                except OSError as error:
                    suffix = f' The new file is saved at {path}; the previous project remains active.' if operation != 'open' else ' The previous project remains active.'
                    raise OSError(str(error) + suffix) from error
        except (ValueError, FileExistsError, self.s.JsonDocumentError) as error:
            return jsonify(status='error', message=str(error)), 422
        except OSError as error:
            return jsonify(status='error', message=str(error)), 500

    def save_snapshot(self, items, sources):
        if not self.s.PROJECT_PATH or not self.s.ITEMS_READY or not self.s.SOURCES_READY:
            raise ValueError('Open a valid project before saving.')
        document = load_project(self.s.PROJECT_PATH)
        document['items'], document['sources'] = items, sources
        write_project(self.s.PROJECT_PATH, document)
        self.s.PROJECT_DOCUMENT['revision'] += 1
        return self.response(document)

    def save(self):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(status='error', message='Expected a JSON object.'), 400
        try:
            with self.s.SAVE_LOCK:
                error = self.check_request(payload)
                if error is not None:
                    return error
                return jsonify(self.save_snapshot(payload.get('items'), payload.get('sources')))
        except (ValueError, self.s.JsonDocumentError) as error:
            return jsonify(status='error', message=str(error)), 422
        except OSError as error:
            return jsonify(status='error', message=str(error)), 500

    def save_extraction(self, payload, record):
        path = self.choose_path(payload, save=True, title='Save selected research as a project', filename='episode.json')
        if not path:
            return self.path_response(path)
        with self.s.SAVE_LOCK:
            if record.get('saved'):
                return jsonify(status='success', **record['saved'])
            error = self.s.project_origin_error(record)
            if error is not None:
                return error
            if self.s.PROJECT_PATH:
                document = copy.deepcopy(load_project(self.s.PROJECT_PATH))
                document.update(project_id=uuid.uuid4().hex, name=os.path.splitext(os.path.basename(path))[0],
                                items=record['items'], sources=record['sources'])
            else:
                mode = 'research' if any('category_part_name' in i for i in record['items']) else 'improv'
                document = new_project(os.path.splitext(os.path.basename(path))[0], record['items'], record['sources'], mode)
            self.write_new(path, document, record['origin_paths'])
            record['saved'] = {'project_token': payload['preview_token'], 'path': path}
            return jsonify(status='success', **record['saved'])

    def save_import(self, payload):
        # Import validation is performed by the existing parser endpoint first.
        with self.s.SAVE_LOCK:
            error = self.check_request(payload)
            if error is not None:
                return error
            items_path, _ = self.s.next_available_import_paths(payload.get('selected_path'))
            folder = os.path.dirname(items_path)
            path = os.path.join(folder, 'scribity_project.json')
            count = 2
            while os.path.lexists(path):
                path = os.path.join(folder, f'scribity_project_{count}.json'); count += 1
            document = new_project(os.path.splitext(os.path.basename(path))[0], payload['items'], payload['sources'], 'research')
            self.write_new(path, document)
            try:
                return jsonify(self.activate(path, document))
            except OSError as error:
                raise OSError(f'{error}. The imported project is saved at {path}; the previous project remains active.') from error
