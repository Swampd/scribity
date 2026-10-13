// Execute the dashboard's actual extraction handlers with fake API/state hooks.
// No browser, network, filesystem writes, or user research documents are involved.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../../dashboard.html'), 'utf8');
const start = html.indexOf('            const projectScopeDescription =');
const end = html.indexOf('            // Helper to get Source info for an Item', start);
const code = html.slice(start, end);

function harness(overrides = {}) {
  const calls = [];
  const context = {
    projectScope: 'draft', projectEmptyDraft: true,
    bulkSelectedIds: new Set(['checked-hidden', 'checked-visible']),
    filteredItems: [{ id_item: 'filtered-only' }],
    selectedRule: 'Filtered category', selectedSubpart: 'Filtered subpart',
    searchQuery: 'search', searchFields: new Set(['quote_original']), activeFilters: new Set(['noSource']),
    projectPreview: { preview_token: 'preview-1' }, projectSaved: { project_token: 'saved-1' },
    projectManualPaths: false, projectItemsPath: '', projectSourcesPath: '',
    itemsDocumentRef: { current: { token: 'items', revision: 1 } },
    sourcesDocumentRef: { current: { token: 'sources', revision: 1 } },
    flushAllPendingDocumentSaves: async () => { calls.push('flush'); },
    api: async (endpoint, options) => {
      calls.push({ endpoint, payload: JSON.parse(options.body) });
      return { status: 'success', preview_token: 'new-preview', project_token: 'new-project',
        items: [], sources: [], items_document: { token: 'new-items', revision: 0 },
        sources_document: { token: 'new-sources', revision: 0 } };
    },
    readApiResponse: async response => response,
    activateItemsDocument: opened => calls.push({ activateItems: opened }),
    activateSourcesDocument: opened => calls.push({ activateSources: opened }),
  };
  for (const name of ['ProjectBusy', 'ProjectPreview', 'ProjectAcknowledged', 'ProjectError',
    'ShowCreateMenu', 'ProjectScope', 'ProjectEmptyDraft', 'ProjectSaved', 'ProjectManualPaths',
    'ProjectItemsPath', 'ProjectSourcesPath', 'ProjectModal', 'SupportTarget', 'LoadError', 'Status']) {
    context[`set${name}`] = value => { calls.push({ set: name, value }); };
  }
  Object.assign(context, overrides);
  vm.runInNewContext(`${code}\nthis.handlers = { previewProject, saveProject, openSavedProject, beginProjectExtraction, projectScopeDescription };`, context);
  return { context, calls, ...context.handlers };
}
const requests = calls => calls.filter(call => call.endpoint);
const activations = calls => calls.filter(call => call.activateItems || call.activateSources);

test('Dashboard JSX parses without a browser', () => {
  const { babelParse } = require('../../node_modules/playwright/lib/transform/babelBundle');
  const script = html.match(/<script type="text\/babel">([\s\S]*?)<\/script>/)[1];
  assert.equal(babelParse(script, 'dashboard.jsx').type, 'File');
});

test('opening the dialog defaults to whole Draft and empty Draft without exporting', () => {
  const h = harness();
  h.beginProjectExtraction();
  assert.ok(h.calls.some(c => c.set === 'ProjectScope' && c.value === 'draft'));
  assert.ok(h.calls.some(c => c.set === 'ProjectEmptyDraft' && c.value === true));
  assert.equal(requests(h.calls).length, 0);
});

test('preview awaits pending edits and uses the resulting document revisions', async () => {
  let resolveFlush;
  const flush = new Promise(resolve => { resolveFlush = resolve; });
  const h = harness({ flushAllPendingDocumentSaves: () => flush });
  const operation = h.previewProject();
  assert.equal(requests(h.calls).length, 0);
  h.context.itemsDocumentRef.current.revision = 2;
  h.context.sourcesDocumentRef.current.revision = 3;
  resolveFlush();
  await operation;
  const [{ payload }] = requests(h.calls);
  assert.equal(payload.items_document.revision, 2);
  assert.equal(payload.sources_document.revision, 3);
  assert.equal(payload.scope, 'draft');
  assert.deepEqual(payload.selected_ids, []); // No unrelated filters restrict Draft.
  assert.equal(payload.empty_draft, true);
  assert.match(h.projectScopeDescription, /do not narrow this scope/);
});

test('checked scope includes hidden checks; filtered scope uses exactly current Library IDs', async () => {
  for (const [scope, expected] of [['checked', ['checked-hidden', 'checked-visible']], ['filtered', ['filtered-only']]]) {
    const h = harness({ projectScope: scope, projectEmptyDraft: false });
    await h.previewProject();
    assert.deepEqual(requests(h.calls)[0].payload.selected_ids, expected);
    assert.equal(requests(h.calls)[0].payload.empty_draft, false);
  }
});

test('failed edit flush blocks preview, save, and opening', async () => {
  for (const handler of ['previewProject', 'saveProject', 'openSavedProject']) {
    const h = harness({ flushAllPendingDocumentSaves: async () => { throw Error('Pending save failed'); } });
    await h[handler]();
    assert.equal(requests(h.calls).length, 0);
    assert.equal(activations(h.calls).length, 0);
    assert.ok(h.calls.some(c => c.set === 'ProjectError' && c.value === 'Pending save failed'));
  }
});

test('save cancellation and server failure leave the current documents active', async () => {
  for (const result of ['canceled', 'failure']) {
    const h = harness({ api: async () => {
      if (result === 'failure') throw Error('Stale preview');
      return { status: 'canceled' };
    } });
    await h.saveProject();
    assert.equal(activations(h.calls).length, 0);
    assert.ok(!h.calls.some(c => c.set === 'ProjectSaved'));
    assert.ok(h.calls.some(c => c.set === 'ProjectError' && c.value));
  }
});

test('saving a pair does not activate it; opening flushes and activates both together', async () => {
  const h = harness();
  await h.saveProject();
  assert.equal(activations(h.calls).length, 0);
  assert.ok(h.calls.some(c => c.set === 'ProjectSaved' && c.value.status === 'success'));
  await h.openSavedProject();
  assert.equal(activations(h.calls).length, 2);
  assert.equal(requests(h.calls)[1].endpoint, 'open_project');
  assert.equal(requests(h.calls)[1].payload.project_token, 'saved-1');
  assert.equal(h.calls.filter(c => c === 'flush').length, 2);
});

test('open failure leaves both existing document sessions intact', async () => {
  const h = harness({ api: async () => { throw Error('Cannot read saved sources'); } });
  await h.openSavedProject();
  assert.equal(activations(h.calls).length, 0);
  assert.ok(!h.calls.some(c => c.set === 'ProjectModal' && c.value === false));
});

test('manual paths use the same saved preview; missing native dialogs expose fallback', async () => {
  const h = harness({ projectManualPaths: true, projectItemsPath: '/new/items.json', projectSourcesPath: '/new/sources.json' });
  await h.saveProject();
  assert.deepEqual(requests(h.calls)[0].payload, { preview_token: 'preview-1', items_path: '/new/items.json', sources_path: '/new/sources.json' });
  const fallback = harness({ api: async () => ({ status: 'gui_unavailable', message: 'Use file paths' }) });
  await fallback.saveProject();
  assert.ok(fallback.calls.some(c => c.set === 'ProjectManualPaths' && c.value === true));
  assert.equal(activations(fallback.calls).length, 0);
});

test('dialogs escape toolbar containing blocks and keep long content scrollable', () => {
  const { babelTransform } = require('../../node_modules/playwright/lib/transform/babelBundle');
  const modalStart = html.indexOf('        const AccessibleModal =');
  const modalEnd = html.indexOf('        // --- UTILITY:', modalStart);
  const compiled = babelTransform(html.slice(modalStart, modalEnd), 'modal.jsx', false, [], []).code;
  const body = { name: 'document body, outside the toolbar' };
  const jsx = (type, props) => ({ type, props });
  const context = {
    require: () => ({ jsx, jsxs: jsx }),
    useRef: () => ({ current: null }), useEffect: () => {},
    document: { body },
    ReactDOM: { createPortal: (child, target) => ({ child, target }) },
  };
  vm.runInNewContext(compiled + '\nthis.renderModal = AccessibleModal;', context);
  assert.equal(context.renderModal({ open: false }), null);
  const rendered = context.renderModal({ open: true, labelledBy: 'test-title', children: 'Long content' });
  assert.equal(rendered.target, body, 'A modal inside the blurred toolbar is clipped above the viewport');
  assert.equal(rendered.child.props.style.position, 'fixed');
  assert.equal(rendered.child.props.style.inset, 0);
  const panel = rendered.child.props.children;
  assert.equal(panel.props.role, 'dialog');
  assert.equal(panel.props.style.maxHeight, 'calc(100dvh - 2rem)');
  assert.equal(panel.props.style.overflowY, 'auto');
});
