const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { babelTransform } = require('../../node_modules/playwright/lib/transform/babelBundle');
const html = fs.readFileSync(require('node:path').join(__dirname, '../../dashboard.html'), 'utf8');
const sources = [
  { id_source: 'a', short_cite: 'Alpha', title: 'First report' },
  { id_source: 'b', short_cite: 'Beta', title: 'Second report' },
  { id_source: 'c', short_cite: '', title: 'Third report' },
];
function findAll(node, predicate) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(child => findAll(child, predicate));
  return [...(predicate(node) ? [node] : []), ...findAll(node.props?.children, predicate)];
}
function picker() {
  const start = html.indexOf('        const SourcePicker =');
  assert.ok(start >= 0, 'Source picker must expose keyboard-accessible component behavior');
  const end = html.indexOf('        // --- RULE EDITOR COMPONENTS ---', start);
  const hooks = [], saves = [], scrolls = [];
  let cursor, effects, dirty, tree;
  const props = { sources, selectedId: 'a', onSelect: id => { saves.push(id); props.selectedId = id; } };
  const jsx = (type, props) => ({ type, props });
  const context = {
    require: () => ({ jsx, jsxs: jsx }), Icon: () => null,
    useState: initial => {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = initial;
      return [hooks[index], value => {
        const next = typeof value === 'function' ? value(hooks[index]) : value;
        if (next !== hooks[index]) { hooks[index] = next; dirty = true; }
      }];
    },
    useRef: initial => { const index = cursor++; return hooks[index] ||= { current: initial }; },
    useEffect: (fn, deps) => {
      const index = cursor++;
      if (!hooks[index] || deps.some((v, i) => v !== hooks[index][i])) effects.push(fn);
      hooks[index] = deps;
    },
  };
  vm.runInNewContext(babelTransform(html.slice(start, end), 'source-picker.jsx', false, [], []).code + '\nthis.SourcePicker = SourcePicker;', context);
  const render = () => {
    do {
      dirty = false; cursor = 0; effects = [];
      tree = context.SourcePicker(props);
      for (const node of findAll(tree, n => n.props?.ref)) {
        node.props.ref.current = { children: findAll(node, n => n.props?.role === 'option').map(option => ({
          scrollIntoView: settings => scrolls.push({ id: option.props.id, block: settings.block }),
        })) };
      }
      effects.forEach(fn => fn());
    } while (dirty);
  };
  render();
  const input = () => findAll(tree, n => n.props?.role === 'combobox')[0];
  const options = () => findAll(tree, n => n.props?.role === 'option');
  return {
    input, options, saves, scrolls, props, render,
    nodes: predicate => findAll(tree, predicate),
    focus() { input().props.onFocus(); render(); },
    change(value) { input().props.onChange({ target: { value } }); render(); },
    blur() { input().props.onBlur(); render(); },
    key(key, extra = {}) {
      const event = { key, preventDefault() { this.prevented = true; }, stopPropagation() {}, ...extra };
      input().props.onKeyDown(event); render(); return event;
    },
  };
}

test('arrow navigation exposes a visible active descendant and Enter commits exactly one source', () => {
  const p = picker();
  assert.equal(p.input().props['aria-expanded'], false);
  assert.equal(p.input().props.value, 'Alpha');
  p.focus();
  const list = p.nodes(n => n.props?.role === 'listbox')[0];
  assert.equal(p.input().props['aria-controls'], list.props.id);
  assert.equal(p.input().props['aria-autocomplete'], 'list');
  assert.ok(p.nodes(n => n.type === 'label' && n.props.htmlFor === p.input().props.id).length);
  p.key('ArrowDown'); p.key('ArrowDown');
  assert.equal(p.input().props['aria-activedescendant'], p.options()[1].props.id);
  assert.equal(p.options()[1].props['aria-selected'], true);
  assert.match(p.options()[1].props.className, /bg-emerald/);
  assert.equal(p.scrolls.at(-1).id, p.options()[1].props.id);
  assert.equal(p.scrolls.at(-1).block, 'nearest');
  p.key('Enter');
  assert.deepEqual(p.saves, ['b']);
  assert.equal(p.input().props.value, 'Beta');
  assert.equal(p.input().props['aria-expanded'], false);
  assert.equal(p.input().props['aria-activedescendant'], undefined);
});

test('filter changes invalidate the active option; empty results cannot select a stale source', () => {
  const p = picker(); p.focus(); p.key('ArrowDown');
  p.change('SECOND');
  assert.equal(p.options().length, 1);
  p.key('Enter'); assert.equal(p.saves.length, 0);
  p.key('ArrowDown'); p.change('no matching source'); p.key('ArrowDown'); p.key('Enter');
  assert.equal(p.options().length, 0);
  assert.equal(p.input().props['aria-activedescendant'], undefined);
  assert.equal(p.saves.length, 0);
  assert.ok(p.nodes(n => n.props?.role === 'status').length);
  p.change('third'); p.key('ArrowUp'); p.key('Enter');
  assert.deepEqual(p.saves, ['c']);
  assert.equal(p.input().props.value, 'Third report');
});

test('Escape, Tab and blur dismiss without selecting; reopening and boundary arrows are safe', () => {
  const p = picker(); p.focus(); p.key('ArrowUp');
  assert.equal(p.input().props['aria-activedescendant'], p.options().at(-1).props.id);
  p.key('ArrowDown');
  assert.equal(p.input().props['aria-activedescendant'], p.options().at(-1).props.id);
  assert.equal(p.key('Escape').prevented, true);
  assert.equal(p.input().props.value, 'Alpha');
  p.key('ArrowDown');
  assert.equal(p.input().props['aria-activedescendant'], p.options()[0].props.id);
  assert.equal(p.key('Tab').prevented, undefined);
  assert.equal(p.input().props['aria-expanded'], false);
  p.focus(); p.blur();
  assert.equal(p.input().props['aria-expanded'], false);
  assert.deepEqual(p.saves, []);
});

test('pointer clicks select without moving input focus; IME and modified keys do not commit', () => {
  const p = picker(); p.focus(); p.key('ArrowDown');
  for (const extra of [{ isComposing: true }, { keyCode: 229 }, { ctrlKey: true }, { metaKey: true }, { altKey: true }]) {
    assert.equal(p.key('Enter', extra).prevented, undefined);
  }
  assert.deepEqual(p.saves, []);
  const option = p.options()[1];
  const event = { preventDefault() { this.prevented = true; } };
  option.props.onMouseDown(event);
  assert.equal(event.prevented, true);
  assert.equal(option.props.tabIndex, -1);
  assert.deepEqual(p.saves, []);
  option.props.onClick(); p.render();
  assert.deepEqual(p.saves, ['b']);
  const unlink = p.nodes(n => n.props?.['aria-label'] === 'Unlink source')[0];
  unlink.props.onClick(); p.render();
  assert.deepEqual(p.saves, ['b', '']);
});

test('external selection changes dismiss stale results, and Inspector mounts a picker per item', () => {
  const p = picker(); p.focus(); p.key('ArrowDown');
  p.props.selectedId = 'c'; p.render();
  assert.equal(p.input().props['aria-expanded'], false);
  assert.equal(p.input().props.value, 'Third report');
  assert.match(html, /<SourcePicker\s+key=\{currentItem.id_item\}/);
  assert.match(html, /onSelect=\{id => handleItemChange\('id_source', id\)\}/);
});

test('clicking a still-focused field reopens dismissed results without clearing an ongoing search', () => {
  const p = picker(); p.focus(); p.key('Escape');
  assert.equal(typeof p.input().props.onClick, 'function');
  p.input().props.onClick(); p.render();
  assert.equal(p.input().props['aria-expanded'], true);
  p.change('second'); p.input().props.onClick(); p.render();
  assert.equal(p.input().props.value, 'second');
  assert.equal(p.options().length, 1);
});
