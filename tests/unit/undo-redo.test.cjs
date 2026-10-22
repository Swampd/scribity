const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../../dashboard.html'), 'utf8');
function harness(overrides = {}) {
  const timers = new Map(), saves = [];
  let timerId = 0;
  const ctx = {unifiedProjectRef:{current:null},projectActionBusyRef:{current:false},view:'library', itemsReady:true, sourcesReady:true, projectModal:false, newDocModal:false, deleteConfirm:null,
    undoStack:{current:[]}, redoStack:{current:[]}, sourceUndoStack:{current:[]}, sourceRedoStack:{current:[]},
    itemsRef:{current:[{id_item:'i',script_notes:'before'}]}, sourcesRef:{current:[{id_source:'s',title:'before'}]},
    inspectorUndoSnapshot:{current:null}, sourceUndoSnapshot:{current:null},
    inspectorSaveTimer:{current:null}, draftSaveTimer:{current:null}, exampleNoteSaveTimer:{current:null}, sourceSaveTimer:{current:null},
    itemsDocumentRef:{current:{token:'items'}},sourcesDocumentRef:{current:{token:'sources'}},
    itemsHistoryDocumentToken:{current:'items'}, sourcesHistoryDocumentToken:{current:'sources'}, UNDO_LIMIT:30,
    setItems: data=>{ctx.itemsRef.current=data;}, setSources:data=>{ctx.sourcesRef.current=data;},
    queueItemsSave: data=>saves.push({type:'items',data:structuredClone(data)}),
    queueSourcesSave: data=>saves.push({type:'sources',data:structuredClone(data)}),
    setStatus:()=>{}, showErrorToast:()=>{}, clearDeleteUndoFor:()=>{},
    clearTimeout:id=>timers.delete(id), setTimeout:fn=>{timers.set(++timerId,fn); return timerId;},
    clearTimerRef:ref=>{timers.delete(ref.current);ref.current=null;},
    document:{activeElement:{tagName:'DIV'}},
    discardStaleItemHistory:()=>{
      if(ctx.itemsHistoryDocumentToken.current === ctx.itemsDocumentRef.current.token) return false;
      ctx.undoStack.current=[];ctx.redoStack.current=[];return true;
    },
    ...overrides,
  };
  const start=html.indexOf('            // --- DOCUMENT HISTORY ---');
  const end=html.indexOf('            useEffect(() => { fetchData(); }, []);',start);
  const source=start<0?'':html.slice(start,end);
  vm.runInNewContext(source+'\nthis.history = typeof restoreHistory === "undefined" ? null : { restoreHistory, handleHistoryShortcut, stageItemEdit, stageSourceEdit, saveItems, saveSources, commitPendingItemEdit, commitPendingSourceEdit };',ctx);
  assert.ok(ctx.history,'History operations must be available');
  return {...ctx.history,ctx,saves,timers,runTimers:()=>{for(const fn of [...timers.values()]) fn();}};
}
function key(h,key,shiftKey=false,extra={}) {
 const e={key,shiftKey,metaKey:true,ctrlKey:false,altKey:false,isComposing:false,defaultPrevented:false,
 target:h.ctx.document.activeElement,preventDefault(){this.defaultPrevented=true;},...extra};
 h.handleHistoryShortcut(e);return e;
}
const item = note => [{id_item:'i',script_notes:note}];
test('Mac/Control undo, uppercase Shift-Z redo, and Control-Y restore and persist the correct snapshots',()=>{
 for(const combo of [{key:'Z',shift:true},{key:'y',shift:false,ctrlKey:true,metaKey:false}]) {
  const h=harness();h.saveItems(item('after'));
  key(h,'z');assert.equal(h.ctx.itemsRef.current[0].script_notes,'before');
  key(h,combo.key,combo.shift,combo);assert.equal(h.ctx.itemsRef.current[0].script_notes,'after');
  assert.equal(h.saves.at(-1).data[0].script_notes,'after');
 }
});
test('text editors, contenteditable, composition, Alt modifiers and dialogs retain their own keyboard behavior',()=>{
 for(const extra of [{tagName:'INPUT'},{tagName:'TEXTAREA'},{tagName:'DIV',isContentEditable:true}]){
  const h=harness();h.saveItems(item('after'));h.ctx.document.activeElement=extra;
  assert.equal(key(h,'z').defaultPrevented,false);assert.equal(h.ctx.itemsRef.current[0].script_notes,'after');
 }
 for(const state of [{projectModal:true},{newDocModal:true},{deleteConfirm:{} }]){
  const h=harness(state);h.saveItems(item('after'));key(h,'z');assert.equal(h.ctx.itemsRef.current[0].script_notes,'after');
 }
 for(const event of [{isComposing:true},{altKey:true},{defaultPrevented:true}]){
  const h=harness();h.saveItems(item('after'));key(h,'z',false,event);assert.equal(h.ctx.itemsRef.current[0].script_notes,'after');
 }
});
test('undo before a note debounce expires cancels the stale save and retains redo',()=>{
 for(const field of ['inspectorSaveTimer','draftSaveTimer','exampleNoteSaveTimer']) {
  const h=harness();h.stageItemEdit(item('typed'),h.ctx[field]);key(h,'z');h.runTimers();
  assert.equal(h.ctx.itemsRef.current[0].script_notes,'before');
  assert.equal(h.saves.at(-1).data[0].script_notes,'before');
  key(h,'Z',true);assert.equal(h.ctx.itemsRef.current[0].script_notes,'typed');
 }
});
test('edits in multiple delayed fields are kept together and undo does not resurrect a stale closure',()=>{
 const h=harness();h.stageItemEdit(item('one'),h.ctx.inspectorSaveTimer);
 h.stageItemEdit([{...h.ctx.itemsRef.current[0],user_02_comments:'two'}],h.ctx.draftSaveTimer);
 h.runTimers();assert.equal(h.saves.at(-1).data[0].user_02_comments,'two');
 key(h,'z');assert.deepEqual(JSON.parse(JSON.stringify(h.ctx.itemsRef.current)),item('before'));
});
test('new edits invalidate redo; immediate actions preserve a separate undo for pending typing',()=>{
 const h=harness();h.saveItems(item('first'));key(h,'z');h.stageItemEdit(item('new'),h.ctx.inspectorSaveTimer);
 key(h,'Z',true);assert.equal(h.ctx.itemsRef.current[0].script_notes,'new');
 h.saveItems([{...h.ctx.itemsRef.current[0],id_script:1}]);key(h,'z');
 assert.equal(h.ctx.itemsRef.current[0].script_notes,'new');assert.equal(h.ctx.itemsRef.current[0].id_script,undefined);
 key(h,'z');assert.equal(h.ctx.itemsRef.current[0].script_notes,'before');
});
test('source edits and deletion have independent undo/redo history',()=>{
 const h=harness({view:'sources'});h.saveItems(item('item unchanged'));
 h.stageSourceEdit([{id_source:'s',title:'edited'}]);key(h,'z');h.runTimers();
 assert.equal(h.ctx.sourcesRef.current[0].title,'before');assert.equal(h.ctx.itemsRef.current[0].script_notes,'item unchanged');
 key(h,'Z',true);assert.equal(h.ctx.sourcesRef.current[0].title,'edited');
 h.saveSources([]);key(h,'z');assert.equal(h.ctx.sourcesRef.current[0].title,'edited');
 assert.equal(h.saves.at(-1).type,'sources');
});
test('history refuses stale document identities and unloaded documents',()=>{
 for(const view of ['library','sources']) {
  const h=harness({view});h.saveItems(item('after'));h.saveSources([]);
  const ref=view==='sources'?h.ctx.sourcesDocumentRef:h.ctx.itemsDocumentRef;
  ref.current={token:'different'};h.saves.length=0;key(h,'z');assert.equal(h.saves.length,0);
 }
 const h=harness();h.saveItems(item('after'));h.ctx.itemsReady=false;h.saves.length=0;key(h,'z');assert.equal(h.saves.length,0);
});
test('history stays bounded and repeated undo works before React renders again',()=>{
 const h=harness();for(let n=0;n<40;n++)h.saveItems(item(String(n)));
 assert.equal(h.ctx.undoStack.current.length,30);
 key(h,'z');key(h,'z');assert.equal(h.ctx.itemsRef.current[0].script_notes,'37');
});

test('history saves use the current document token after Save As, not an older render token',()=>{
 const start=html.indexOf('            const queueItemsSave =');
 const end=html.indexOf('            const flushPendingDocumentSaves =',start);
 const jobs=[];
 const ctx={unifiedProjectRef:{current:null},itemsReady:true,sourcesReady:true,schemaModeRef:{current:'research'},
  itemsDocument:{token:'old-items'},sourcesDocument:{token:'old-sources'},
  itemsDocumentRef:{current:{token:'new-items',revision:2}},sourcesDocumentRef:{current:{token:'new-sources',revision:3}},
  itemsSaveQueue:{},sourcesSaveQueue:{},enqueueSave:(_,job)=>jobs.push(job),denormalizeItems:x=>x};
 vm.runInNewContext(html.slice(start,end)+'\nthis.saveItems = queueItemsSave;this.saveSources = queueSourcesSave;',ctx);
 ctx.saveItems(item('restored'));ctx.saveSources([{id_source:'s'}]);
 assert.equal(jobs[0].originDocument.token,'new-items');assert.equal(jobs[1].originDocument.token,'new-sources');
 assert.equal(JSON.parse(jobs[0].serialize(ctx.itemsDocumentRef.current)).document_token,'new-items');
});

test('opening another sources document clears only source history and pending source typing',()=>{
 const start=html.indexOf('            const resetSourcesDocumentSession =');
 const end=html.indexOf('            const activateItemsDocument =',start);
 const h=harness();h.ctx.resetSaveQueueForActivation=()=>{};h.ctx.sourcesSaveQueue={};
 for(const name of ['DeleteConfirm','SelectedSourceId','SrcQuery','SrcOpen']) h.ctx['set'+name]=()=>{};
 h.saveItems(item('keep'));h.stageSourceEdit([{id_source:'s',title:'old pending'}]);
 h.ctx.sourceRedoStack.current.push([]);
 vm.runInNewContext(html.slice(start,end)+'\nthis.reset = resetSourcesDocumentSession;',h.ctx);
 h.ctx.reset({token:'next-source-document'});
 assert.equal(h.ctx.undoStack.current.length,1);
 assert.equal(h.ctx.sourceUndoStack.current.length,0);assert.equal(h.ctx.sourceRedoStack.current.length,0);
 assert.equal(h.ctx.sourceUndoSnapshot.current,null);assert.equal(h.timers.size,0);
 assert.equal(h.ctx.sourcesHistoryDocumentToken.current,'next-source-document');
});
