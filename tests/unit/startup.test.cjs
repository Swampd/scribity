const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { babelTransform } = require('../../node_modules/playwright/lib/transform/babelBundle');

for (const unified of [false, true]) test(`full App loads ${unified ? 'a unified project' : 'a legacy pair'} without startup errors`, async () => {
  const html = fs.readFileSync(require('node:path').join(__dirname, '../../dashboard.html'), 'utf8');
  const script = html.match(/<script type="text\/babel">([\s\S]*?)<\/script>/)[1];
  const hooks = [], effects = [], requests = [];
  let cursor = 0, App, tree, revision = 0, identity = 0, lastSaved;
  const projectInfo = { name: 'Fixture project', filename: 'fixture-project.json', path: '/tmp/fixture-project.json', schema_mode: 'improv' };
  const jsx = (type, props) => ({ type, props });
  const context = {
    require: () => ({ jsx, jsxs: jsx }),
    React: {
      useState(initial) {
        const i = cursor++;
        if (!(i in hooks)) hooks[i] = typeof initial === 'function' ? initial() : initial;
        return [hooks[i], next => { hooks[i] = typeof next === 'function' ? next(hooks[i]) : next; }];
      },
      useRef(initial) { const i = cursor++; return hooks[i] ||= { current: initial }; },
      useMemo: fn => fn(), useCallback: fn => fn,
      useEffect(fn, deps) {
        const i = cursor++;
        if (!hooks[i] || deps.some((dep, index) => dep !== hooks[i][index])) effects.push(fn);
        hooks[i] = deps;
      },
      useLayoutEffect: () => {},
    },
    ReactDOM: { createRoot: () => ({ render: element => { App = element.type; tree = App(); } }) },
    document: { getElementById: () => ({}), addEventListener() {}, removeEventListener() {} },
    window: { addEventListener() {}, removeEventListener() {} },
    setTimeout: () => 1, clearTimeout() {}, console,
    crypto: { randomUUID: () => `new-${++identity}` },
    fetch: async (url, options) => {
      requests.push(url);
      if (url === '/api/project/save') {
        const payload = JSON.parse(options.body);
        assert.equal(payload.items_document.revision, revision);
        assert.deepEqual(payload.items_document, payload.sources_document);
        lastSaved = payload;
        revision++;
        return { ok: true, json: async () => ({ status: 'success', notices: [],
          items_document: { token: 'items', revision }, sources_document: { token: 'items', revision } }) };
      }
      if (url === '/api/project/action') {
        const payload = JSON.parse(options.body);
        assert.equal(payload.operation, 'save_as');
        assert.equal(payload.items_document.revision, revision);
        revision = 0;
        return { ok: true, json: async () => ({ status:'success', items:lastSaved.items, sources:lastSaved.sources,
          project:{...projectInfo,filename:'copy.json',path:'/tmp/copy.json'},
          items_filename:'copy.json',sources_filename:'copy.json',
          items_document:{token:'items',revision},sources_document:{token:'items',revision},notices:[] }) };
      }
      assert.equal(options, undefined, 'Startup must not write research data');
      assert.equal(url, '/api/data');
      return { ok: true, json: async () => ({
        items: [{ id_item: 'fixture', quote_original: 'Startup fixture', rule_name: [], id_script: 0 }],
        sources: [{ id_source: 'source', title: 'Fixture source' }],
        items_filename: 'fixture-items.json', sources_filename: 'fixture-sources.json',
        ...(unified ? { project: projectInfo, notices: [] } : {}),
        items_document: { token: 'items', revision: 0 }, sources_document: { token: unified ? 'items' : 'sources', revision: 0 },
      }) };
    },
  };
  vm.runInNewContext(babelTransform(script, 'dashboard-startup.jsx', false, [], []).code, context);
  assert.ok(tree, 'Initial App render must produce UI');
  effects.splice(0).forEach(effect => effect());
  await new Promise(resolve => setImmediate(resolve));
  cursor = 0; tree = App();
  effects.splice(0).forEach(effect => effect());
  assert.deepEqual(requests, ['/api/data']);
  const rendered = JSON.stringify(tree);
  assert.match(rendered, unified ? /Project loaded/ : /Loaded \(improv\)/);
  assert.match(rendered, /Startup fixture/);
  assert.match(rendered, unified ? /fixture-project.json/ : /fixture-sources.json/);
  if (unified) { assert.match(rendered, /Project history/); assert.doesNotMatch(rendered, /Convert loaded pair/); }
  assert.doesNotMatch(rendered, /Load Error|is not defined/);

  const find = (node, predicate) => {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(child => find(child, predicate));
    return [...(predicate(node) ? [node] : []), ...find(node.props?.children, predicate)];
  };
  const toolbar = find(tree, node => node.props?.['aria-label'] === 'Application controls')[0];
  assert.ok(toolbar, 'Toolbar must have an identifiable responsive container');
  assert.match(toolbar.props.className, /flex-wrap/);
  assert.doesNotMatch(toolbar.props.className, /(?:^|\s)h-14(?:\s|$)|overflow-hidden/);
  const create = find(toolbar, node => node.type === 'button' && node.props.title === 'Create new...')[0];
  assert.match(JSON.stringify(create.props.children), /New/);
  assert.equal(create.props['aria-expanded'], false);
  create.props.onClick();
  cursor = 0; tree = App();
  const menu = find(tree, node => node.props?.id === 'create-new-menu')[0];
  assert.ok(menu, 'New button must open its menu');
  assert.match(JSON.stringify(menu), /New Item/);
  assert.match(JSON.stringify(menu), /New Project/);
  if (unified) {
    const render = () => { cursor=0; tree=App(); effects.splice(0).forEach(effect=>effect()); };
    const settle = async () => { await new Promise(resolve=>setImmediate(resolve)); render(); };
    const button = text => find(tree, n => n.type==='button' && JSON.stringify(n.props.children)?.includes(text))[0];
    button('New Item').props.onClick(); await settle();
    assert.equal(lastSaved.items.length,2); assert.equal(lastSaved.sources.length,1);
    find(tree,n=>n.props?.title==='Create new...')[0].props.onClick(); render();
    button('New Source').props.onClick(); await settle();
    assert.equal(lastSaved.items.length,2); assert.equal(lastSaved.sources.length,2);
    button('↶ Undo').props.onClick(); await settle();
    assert.equal(lastSaved.sources.length,1); assert.equal(lastSaved.items.length,2);
    await button('Save As…').props.onClick(); await settle();
    assert.match(JSON.stringify(tree),/copy.json/);
    button('↶ Undo').props.onClick(); await settle();
    assert.equal(lastSaved.items.length,1); assert.equal(lastSaved.sources.length,1);
    button('↷ Redo').props.onClick(); await settle();
    assert.equal(lastSaved.items.length,2);
    assert.ok(requests.every(url => ['/api/data','/api/project/action','/api/project/save'].includes(url)));
  }
});
