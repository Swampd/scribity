// Component/handler tests only. This does not launch or automate a browser.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { babelTransform } = require('../../node_modules/playwright/lib/transform/babelBundle');
const html = fs.readFileSync(require('node:path').join(__dirname, '../../dashboard.html'), 'utf8');
const start = html.indexOf('        // --- DRR IMPORT REVIEW ---');
const end = html.indexOf('        const AdditionalInfoManager =', start);
const source = start < 0 ? '' : html.slice(start, end);
const jsx = (type, props) => ({ type, props });
const context = { require: () => ({ jsx, jsxs: jsx }) };
vm.runInNewContext(babelTransform(source, 'drr.jsx', false, [], []).code + `
this.components = {
  getDrrImportReview: typeof getDrrImportReview === 'undefined' ? null : getDrrImportReview,
  ReportMetadata: typeof ReportMetadata === 'undefined' ? null : ReportMetadata,
  DrrImportReview: typeof DrrImportReview === 'undefined' ? null : DrrImportReview,
};`, context);
const { getDrrImportReview, ReportMetadata, DrrImportReview } = context.components;
function nodes(node, predicate) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(child => nodes(child, predicate));
  return [...(predicate(node) ? [node] : []), ...nodes(node.props?.children, predicate)];
}
const record = { report_provenance: { report_id: 'sample', metadata: { publishedOn: null, custom: { keep: ['nested'] } } } };

test('incomplete parser results cannot be saved or appended, even without collision errors', () => {
  assert.equal(typeof getDrrImportReview, 'function');
  for (const result of [{ can_import: false }, {}, { can_import: true, diagnostics: [{ severity: 'error', message: 'Missing source' }] }]) {
    const review = getDrrImportReview(result, []);
    assert.equal(review.canSave, false);
    assert.equal(review.canAppend, false);
  }
  assert.equal(getDrrImportReview({ can_import: true, diagnostics: [{ severity: 'warning' }] }, []).canSave, true);
});

test('an already imported report can be saved separately but cannot be appended again', () => {
  assert.equal(typeof getDrrImportReview, 'function');
  const review = getDrrImportReview({ can_import: true, sources: [record] }, [record]);
  assert.equal(review.canSave, true);
  assert.equal(review.canAppend, false);
  assert.deepEqual(Array.from(review.repeatedReports), ['sample']);
});

test('report metadata is readable and has no editable controls to corrupt nested objects', () => {
  assert.equal(typeof ReportMetadata, 'function');
  const tree = ReportMetadata({ report: record.report_provenance });
  assert.equal(nodes(tree, n => ['input', 'textarea', 'select'].includes(n.type)).length, 0);
  assert.ok(JSON.stringify(tree).includes('Unknown / unpublished'));
  assert.ok(JSON.stringify(tree).includes('nested'));
});

test('diagnostic review includes line numbers and original skipped content', () => {
  assert.equal(typeof DrrImportReview, 'function');
  const result = { can_import: false, diagnostics: [{ severity: 'error', filename: 'report.mdx', line: 21,
    code: 'uncited_text', message: 'Missing citation', excerpt: 'Do not lose this passage.' }] };
  const tree = DrrImportReview({ result, review: getDrrImportReview(result, []) });
  assert.ok(nodes(tree, n => n.props?.role === 'alert').length);
  const text = JSON.stringify(tree);
  assert.ok(text.includes('Do not lose this passage.'));
  assert.ok(text.includes('report.mdx:21'));
});

test('additional information editor does not offer report provenance as an editable scalar', () => {
  const constant = html.slice(html.indexOf('        const RENDERED_ELSEWHERE ='), html.indexOf('        // --- RULE EDITOR'));
  const component = html.slice(html.indexOf('        const AdditionalInfoManager ='), html.indexOf('        function App()'));
  const ctx = { require: () => ({ jsx, jsxs: jsx }), Icon: () => null,
    useMemo: fn => fn(), useState: value => [value === false ? true : value, () => {}],
    EXAMPLE_EXCLUDED_KEYS: [], ADDITIONAL_INFO_FIELDS: [], TEXTAREA_FIELDS: [] };
  vm.runInNewContext(babelTransform(constant + component, 'additional.jsx', false, [], []).code + '\nthis.component = AdditionalInfoManager;', ctx);
  const tree = ctx.component({ item: { id_item: '1', ...record, custom_note: 'keep editable' }, onChange: () => {} });
  const inputs = nodes(tree, n => ['input', 'textarea'].includes(n.type));
  assert.ok(inputs.some(n => n.props.value === 'keep editable'));
  assert.ok(!inputs.some(n => n.props.id === 'additional-field-report_provenance'));
});

function importHandler(label, overrides = {}) {
  const { babelParse } = require('../../node_modules/playwright/lib/transform/babelBundle');
  const script = html.match(/<script type="text\/babel">([\s\S]*?)<\/script>/)[1];
  const ast = babelParse(script, 'dashboard.jsx');
  function walk(node, predicate) {
    if (!node || typeof node !== 'object') return [];
    return [...(predicate(node) ? [node] : []), ...Object.values(node).flatMap(value =>
      Array.isArray(value) ? value.flatMap(v => walk(v, predicate)) : walk(value, predicate))];
  }
  const button = walk(ast, n => n.type === 'JSXElement' && n.openingElement.name.name === 'button'
    && n.children.some(child => walk(child, n => n.type === 'StringLiteral' && n.value === label).length))[0];
  const handler = button.openingElement.attributes.find(a => a.name?.name === 'onClick').value.expression;
  const calls = [];
  const original = [{ id_item: 'old', script_notes: 'before pending edit' }];
  const ctx = {
    unifiedProjectRef: { current: null },
    parseResult: { items: [{ id_item: 'imported' }], sources: [], can_import: true, diagnostics: [] },
    importReview: { canSave: true, canAppend: true }, getDrrImportReview,
    items: original, sources: [], itemsRef: { current: original }, sourcesRef: { current: [] },
    itemsDocumentRef: { current: { token: 'items', revision: 0 } }, sourcesDocumentRef: { current: { token: 'sources', revision: 0 } },
    schemaModeRef: { current: 'research' }, normalizeItems: x => x, denormalizeItems: x => x,
    flushAllPendingDocumentSaves: async () => {},
    api: async (endpoint, options) => { calls.push({ endpoint, payload: JSON.parse(options.body) }); return {}; },
    readApiResponse: async x => x, applyDocumentState: () => {},
    undoStack: { current: [] }, redoStack: { current: [] }, UNDO_LIMIT: 20,
  };
  for (const name of ['ParseSaving', 'ParseError', 'Status', 'Items', 'Sources', 'ParseResult', 'View'])
    ctx['set' + name] = value => calls.push({ state: name, value });
  Object.assign(ctx, overrides);
  vm.runInNewContext('this.run = (' + script.slice(handler.start, handler.end) + ')', ctx);
  return { run: ctx.run, ctx, calls };
}

test('append takes its research snapshot after pending edits finish saving', async () => {
  const h = importHandler('Append to Current');
  h.ctx.flushAllPendingDocumentSaves = async () => {
    h.ctx.itemsRef.current = [{ id_item: 'old', script_notes: 'latest pending edit' }];
    h.ctx.itemsDocumentRef.current.revision = 1;
  };
  await h.run();
  const request = h.calls.find(c => c.endpoint === 'append_import');
  assert.ok(request);
  assert.equal(request.payload.items[0].script_notes, 'latest pending edit');
  assert.equal(request.payload.items_document.revision, 1);
  assert.equal(request.payload.can_import, true);
});

test('append stops if flushing edits fails or the active document changes during the flush', async () => {
  for (const fail of [true, false]) {
    const h = importHandler('Append to Current');
    h.ctx.flushAllPendingDocumentSaves = async () => {
      if (fail) throw new Error('pending edit failed');
      h.ctx.itemsDocumentRef.current = { token: 'other-document', revision: 0 };
    };
    await h.run();
    assert.equal(h.calls.filter(c => c.endpoint).length, 0);
    assert.ok(h.calls.some(c => c.state === 'ParseError'));
  }
});

test('save to new file also stops when documents switch during pending saves', async () => {
  const h = importHandler('Save to New File');
  h.ctx.flushAllPendingDocumentSaves = async () => {
    h.ctx.sourcesDocumentRef.current = { token: 'other-sources', revision: 0 };
  };
  await h.run();
  assert.equal(h.calls.filter(c => c.endpoint).length, 0);
  assert.ok(h.calls.some(c => c.state === 'ParseError'));
});
