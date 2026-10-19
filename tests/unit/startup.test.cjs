const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { babelTransform } = require('../../node_modules/playwright/lib/transform/babelBundle');

test('full App renders, runs mount effects, and loads both documents without startup errors', async () => {
  const html = fs.readFileSync(require('node:path').join(__dirname, '../../dashboard.html'), 'utf8');
  const script = html.match(/<script type="text\/babel">([\s\S]*?)<\/script>/)[1];
  const hooks = [], effects = [], requests = [];
  let cursor = 0, App, tree;
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
    fetch: async (url, options) => {
      requests.push(url);
      assert.equal(options, undefined, 'Startup must not write research data');
      assert.equal(url, '/api/data');
      return { ok: true, json: async () => ({
        items: [{ id_item: 'fixture', quote_original: 'Startup fixture', rule_name: [], id_script: 0 }],
        sources: [{ id_source: 'source', title: 'Fixture source' }],
        items_filename: 'fixture-items.json', sources_filename: 'fixture-sources.json',
        items_document: { token: 'items', revision: 0 }, sources_document: { token: 'sources', revision: 0 },
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
  assert.match(rendered, /Loaded \(improv\)/);
  assert.match(rendered, /Startup fixture/);
  assert.match(rendered, /fixture-sources.json/);
  assert.doesNotMatch(rendered, /Load Error|is not defined/);
});
