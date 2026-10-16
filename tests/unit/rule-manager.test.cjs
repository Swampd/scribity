const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { babelTransform } = require('../../node_modules/playwright/lib/transform/babelBundle');
const html = fs.readFileSync(path.join(__dirname, '../../dashboard.html'), 'utf8');
const source = html.slice(html.indexOf('        const RuleRow ='), html.indexOf('        // --- EXAMPLE MANAGER COMPONENT ---'));
const jsx = (type, props) => ({ type, props });
const context = {
  require: () => ({ jsx, jsxs: jsx }),
  useMemo: fn => fn(), useState: initial => [initial, () => {}],
  Icon: () => null, // Essential delete control must work without the icon library.
};
vm.runInNewContext(babelTransform(source, 'rules.jsx', false, [], []).code + '\nthis.components = {RuleRow, RuleManager};', context);
const { RuleRow, RuleManager } = context.components;
const labels = { rule: 'Rule', rules: 'Rules', addRule: 'Add Another Rule', selectRule: 'Select Rule' };
function findAll(node, predicate) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(child => findAll(child, predicate));
  return [...(predicate(node) ? [node] : []), ...findAll(node.props?.children, predicate)];
}
function manager(item) {
  const saves = [];
  const tree = RuleManager({ item, ruleHierarchy: [], allItems: [], labels, onSave: next => saves.push(next) });
  return { saves, tree, rows: findAll(tree, node => node.type === RuleRow) };
}
const fixture = () => ({
  id_item: 'keep-id', rule_name: ['First', 'Remove this', 'Third'], rule_number: ['1', '2', '3'],
  subpart_name: ['A', 'B', 'C'], subpart_number: ['a', 'b', 'c'], id_subpart: [10, 20, 30],
  id_script: 7, nested_under: 'parent', user_02_comments: 'Keep notes', custom: { tags: ['keep'] },
});

test('first rule is protected; every additional row has an always-present local trash icon', () => {
  const m = manager(fixture());
  m.rows.forEach((row, index) => {
    const rendered = RuleRow(row.props);
    const buttons = findAll(rendered, node => node.type === 'button');
    assert.equal(buttons.length, index === 0 ? 0 : 1);
    if (index > 0) {
      const button = buttons[0];
      assert.equal(button.props['aria-label'], `Delete rule row ${index + 1}`);
      assert.equal(button.props.type, 'button');
      assert.ok(!/opacity-0|reveal-action/.test(button.props.className));
      const icons = findAll(button, node => node.type === 'svg');
      assert.equal(icons.length, 1);
      assert.equal(icons[0].props['aria-hidden'], 'true');
      assert.ok(findAll(icons[0], node => node.type === 'path').length > 0);
    }
  });
});

test('removing the middle assignment keeps all five arrays aligned and preserves other metadata', () => {
  const item = fixture();
  const original = structuredClone(item);
  const m = manager(item);
  const button = findAll(RuleRow(m.rows[1].props), node => node.type === 'button')[0];
  button.props.onClick();
  assert.equal(m.saves.length, 1);
  const expected = { ...item };
  for (const field of ['rule_name', 'rule_number', 'subpart_name', 'subpart_number', 'id_subpart']) {
    expected[field] = [item[field][0], item[field][2]];
  }
  assert.deepEqual(JSON.parse(JSON.stringify(m.saves[0])), expected);
  assert.deepEqual(item, original);
});

test('delete handler rejects the first row and invalid indexes without changing anything', () => {
  const m = manager(fixture());
  for (const index of [0, -1, 3, 1.5, '1']) m.rows[0].props.onDelete(index);
  assert.equal(m.saves.length, 0);
});

test('an unused extra row can be removed and the only required row remains', () => {
  const m = manager({ id_item: 'empty-extra', rule_name: ['First', ''] });
  m.rows[1].props.onDelete(1);
  assert.deepEqual(JSON.parse(JSON.stringify(m.saves[0].rule_name)), ['First']);
  const single = manager(m.saves[0]);
  assert.equal(single.rows.length, 1);
  single.rows[0].props.onDelete(0);
  assert.equal(single.saves.length, 0);
  assert.equal(manager({ id_item: 'empty' }).rows.length, 1);
});
