const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../../dashboard.html'), 'utf8');
function harness() {
  const timers = new Map(), jobs = [], changes = [];
  const ctx = {
    unifiedProjectRef: { current: { name: 'Fixture' } }, projectUndoStack: { current: [] }, projectRedoStack: { current: [] },
    projectPendingSnapshot: { current: null }, projectEditTimer: { current: null }, projectHistoryToken: { current: 'one' },
    projectRawItemsRef: { current: [{ id_item: 'i', category_part_name: ['A'], category_part_number: [], rule_name: ['opaque metadata'], custom: { x: 1 } }] },
    itemsRef: { current: [{ id_item: 'i', category_part_name: undefined, rule_name: ['A'], rule_number: [], custom: { x: 1 } }] },
    sourcesRef: { current: [{ id_source: 's', title: 'before' }] }, schemaModeRef: { current: 'improv' },
    itemsDocumentRef: { current: { token: 'one', revision: 0 } }, sourcesDocumentRef: { current: { token: 'one', revision: 0 } },
    itemsReady: true, sourcesReady: true, UNDO_LIMIT: 30, itemsSaveQueue: { current: {} },
    setItems: value => { ctx.itemsRef.current = value; }, setSources: value => { ctx.sourcesRef.current = value; },
    setProjectNotices: () => {}, clearDeleteUndoFor: () => {}, showErrorToast: value => changes.push(value), setStatus: () => {},
    normalizeItems: (items, mode) => mode === 'research' ? items.map(({ category_part_name, category_part_number, ...rest }) => ({ ...rest, rule_name: category_part_name || [], rule_number: category_part_number || [] })) : items,
    denormalizeItems: items => items,
    enqueueSave: (_, job) => jobs.push(job), applyDocumentState: (kind, doc) => { ctx[kind+'DocumentRef'].current = doc; },
    clearTimerRef: ref => { timers.delete(ref.current); ref.current = null; },
    setTimeout: fn => { const id = {}; timers.set(id, fn); return id; },
  };
  const start = html.indexOf('            // --- UNIFIED PROJECT OPERATIONS ---');
  const end = html.indexOf('            // --- LEGACY SAVE ADAPTERS ---', start);
  assert.ok(start >= 0 && end > start, 'Unified project operations must exist');
  vm.runInNewContext(html.slice(start, end) + '\nthis.ops = {recordProjectEdit, stageProjectEdit, commitProjectEdit, restoreProjectHistory, queueProjectSave, encodeProjectItems};', ctx);
  return {ctx, jobs, timers, ...ctx.ops};
}
test('item and source changes share one chronological undo/redo history and one full-project save', () => {
  const h = harness(); const before = h.ctx.itemsRef.current;
  h.recordProjectEdit([{id_item:'i',script_notes:'after'}], h.ctx.sourcesRef.current);
  h.recordProjectEdit(h.ctx.itemsRef.current, [{id_source:'s',title:'after'}]);
  h.restoreProjectHistory('undo');
  assert.equal(h.ctx.sourcesRef.current[0].title, 'before');
  assert.equal(h.ctx.itemsRef.current[0].script_notes, 'after');
  h.restoreProjectHistory('undo'); assert.equal(h.ctx.itemsRef.current, before);
  h.restoreProjectHistory('redo'); assert.equal(h.ctx.itemsRef.current[0].script_notes, 'after');
  const payload = JSON.parse(h.jobs.at(-1).serialize({token:'one',revision:4}));
  assert.equal(payload.items[0].script_notes, 'after'); assert.equal(payload.sources[0].title, 'before');
  assert.equal(payload.items_document.revision,4); assert.deepEqual(payload.items_document,payload.sources_document);
});
test('pending edits across both lists are undone together and their timer cannot overwrite undo', () => {
  const h = harness();
  h.stageProjectEdit([{id_item:'i',script_notes:'typed'}], h.ctx.sourcesRef.current);
  h.stageProjectEdit(h.ctx.itemsRef.current, [{id_source:'s',title:'typed'}]);
  h.restoreProjectHistory('undo');
  assert.equal(h.timers.size,0); assert.equal(h.ctx.sourcesRef.current[0].title,'before');
  assert.equal(h.ctx.itemsRef.current[0].script_notes,undefined);
  h.restoreProjectHistory('redo'); assert.equal(h.ctx.sourcesRef.current[0].title,'typed');
  h.recordProjectEdit([],[]); assert.equal(h.ctx.projectRedoStack.current.length,0);
});
test('research serialization changes only edited fields and retains overlapping legacy metadata', () => {
  const h = harness(); h.ctx.schemaModeRef.current='research';
  const raw=h.ctx.projectRawItemsRef.current;
  const normalized=h.ctx.normalizeItems(raw,'research');
  assert.deepEqual(JSON.parse(JSON.stringify(h.encodeProjectItems(normalized))),raw);
  const edited=h.encodeProjectItems([{...normalized[0],script_notes:'new',rule_name:['B']}])[0];
  assert.equal(edited.rule_name[0],'opaque metadata'); assert.equal(edited.category_part_name[0],'B');
  assert.equal(edited.custom.x,1); assert.equal(edited.script_notes,'new');
});
test('history cannot cross project sessions and saves are blocked without both lists ready', () => {
  const h=harness();h.recordProjectEdit([],[]); const count=h.jobs.length;
  h.ctx.itemsDocumentRef.current={token:'two',revision:0}; h.restoreProjectHistory('undo');
  assert.equal(h.jobs.length,count); assert.equal(h.ctx.projectUndoStack.current.length,0);
  h.ctx.sourcesReady=false; h.queueProjectSave([],[]); assert.equal(h.jobs.length,count);
});
