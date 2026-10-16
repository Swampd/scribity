const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

// Serve only the dashboard. API responses below are entirely in memory; these
// tests cannot open, save, or change the user's configured JSON documents.
const dashboard = fs.readFileSync(path.join(__dirname, '..', '..', 'dashboard.html'));
let server;
let baseURL;

test.beforeAll(async () => {
  server = http.createServer((request, response) => {
    if (request.url !== '/') {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    response.end(dashboard);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  baseURL = `http://127.0.0.1:${server.address().port}/`;
});

test.afterAll(async () => {
  if (server) await new Promise(resolve => server.close(resolve));
});

test.beforeEach(async ({ page }) => {
  page.scribityPageErrors = [];
  page.on('pageerror', error => page.scribityPageErrors.push(error.message));
});

test.afterEach(async ({ page }) => {
  expect(page.scribityPageErrors).toEqual([]);
});

function useFakeDocuments(page, { cancelItemsOpen = false } = {}) {
  const state = {
    items: {
      a: [{ id_item: 'item-a', quote_original: 'Document A original', contains_example: false }],
      b: [{ id_item: 'item-b', quote_original: 'Document B must remain unchanged', contains_example: false }],
    },
    sources: {
      a: [],
      b: [],
    },
    activeItems: 'a',
    activeSources: 'a',
    itemsVersion: { token: 'items-a', revision: 0 },
    sourcesVersion: { token: 'sources-a', revision: 0 },
    itemSaves: [],
    importSaves: [],
  };

  page.route('**/api/**', async route => {
    const endpoint = new URL(route.request().url()).pathname.replace('/api/', '');
    const supplied = route.request().postDataJSON?.() || {};
    let result;
    let status = 200;

    switch (endpoint) {
      case 'data':
        result = {
          status: 'success',
          items: state.items[state.activeItems],
          sources: state.sources[state.activeSources],
          items_filename: `items-${state.activeItems}.json`,
          sources_filename: `sources-${state.activeSources}.json`,
          items_document: state.itemsVersion,
          sources_document: state.sourcesVersion,
        };
        break;
      case 'save_items':
        if (supplied.document_token !== state.itemsVersion.token || supplied.revision !== state.itemsVersion.revision) {
          status = 409;
          result = { status: 'error', kind: 'stale_document', message: 'Stale document' };
          break;
        }
        state.items[state.activeItems] = structuredClone(supplied.data);
        state.itemSaves.push({ document: state.activeItems, data: structuredClone(supplied.data) });
        state.itemsVersion = { ...state.itemsVersion, revision: state.itemsVersion.revision + 1 };
        result = { status: 'success', document: state.itemsVersion };
        break;
      case 'open_items':
        if (cancelItemsOpen) {
          result = { status: 'canceled' };
          break;
        }
        state.activeItems = 'b';
        state.itemsVersion = { token: 'items-b', revision: 0 };
        result = {
          status: 'success',
          data: state.items.b,
          filename: 'items-b.json',
          document: state.itemsVersion,
        };
        break;
      case 'open_sources':
        state.activeSources = 'b';
        state.sourcesVersion = { token: 'sources-b', revision: 0 };
        result = {
          status: 'success',
          data: state.sources.b,
          filename: 'sources-b.json',
          document: state.sourcesVersion,
        };
        break;
      case 'parse_drr_picker':
        result = {
          status: 'success',
          selected_path: '/reports/1946_Operation_Highjump',
          items: [{ id_item: 'imported-item', quote_original: 'Imported sentence' }],
          sources: [{ id_source: 'imported-source' }],
          files: [{ title: 'Operation Highjump', stats: { items: 1, sources: 1 } }],
          stats: { total_items: 1, total_sources: 1 },
          collisions: [],
        };
        break;
      case 'save_import_document':
        state.importSaves.push(structuredClone(supplied));
        state.items[state.activeItems] = structuredClone(supplied.items);
        state.sources[state.activeSources] = structuredClone(supplied.sources);
        state.itemsVersion = { token: 'imported-items', revision: 0 };
        state.sourcesVersion = { token: 'imported-sources', revision: 0 };
        result = {
          status: 'success',
          items_filename: 'scribity_items.json',
          sources_filename: 'scribity_sources.json',
          items_document: state.itemsVersion,
          sources_document: state.sourcesVersion,
        };
        break;
      default:
        status = 500;
        result = { status: 'error', message: `Unexpected API endpoint: ${endpoint}` };
    }

    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(result) });
  });
  return state;
}

async function openAAndEdit(page, { waitForSave = true } = {}) {
  await expect(page.getByTitle('Open Items JSON')).toContainText('items-a.json');
  await page.getByText('Document A original', { exact: false }).click();
  const quote = page.locator('#quote-textarea');
  await expect(quote).toHaveValue('Document A original');
  await quote.fill('Document A edited');
  if (waitForSave) await expect(page.getByText('Saved', { exact: true })).toBeVisible();
  return quote;
}

test('opening Items flushes the edit and prevents Undo from writing A into B', async ({ page }, testInfo) => {
  const state = useFakeDocuments(page);
  await page.goto(baseURL);
  await expect(page).toHaveTitle('Scribity');
  await expect(page.getByRole('button', { name: 'Library', exact: true })).toBeVisible();
  await openAAndEdit(page, { waitForSave: false });
  await page.getByTitle('Open Items JSON').click();
  await expect(page.getByTitle('Open Items JSON')).toContainText('items-b.json');
  await expect(page.getByText('Document B must remain unchanged', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Library', exact: true })).toHaveClass(/bg-indigo-600/);
  // The navigation buttons animate their colors; capture the settled state.
  await page.waitForTimeout(200);
  await page.screenshot({ path: testInfo.outputPath('opened-document-b.png') });

  const savesBeforeUndo = state.itemSaves.length;
  await page.keyboard.press('ControlOrMeta+z');
  await expect(page.getByText('Document B must remain unchanged', { exact: false })).toBeVisible();
  expect(state.items.a[0].quote_original).toBe('Document A edited');
  expect(state.items.b[0].quote_original).toBe('Document B must remain unchanged');
  expect(state.itemSaves).toHaveLength(savesBeforeUndo);
});

test('cancelled Items open retains the current document and its Undo history', async ({ page }) => {
  const state = useFakeDocuments(page, { cancelItemsOpen: true });
  await page.goto(baseURL);
  await openAAndEdit(page);
  await page.getByTitle('Open Items JSON').click();
  await expect(page.getByText('Canceled', { exact: true })).toBeVisible();
  await page.keyboard.press('ControlOrMeta+z');
  await expect(page.locator('#quote-textarea')).toHaveValue('Document A original');
  await expect.poll(() => state.items.a[0].quote_original).toBe('Document A original');
  expect(state.items.b[0].quote_original).toBe('Document B must remain unchanged');
});

test('opening Sources preserves valid Items Undo history', async ({ page }) => {
  const state = useFakeDocuments(page);
  await page.goto(baseURL);
  await openAAndEdit(page);
  await page.getByTitle('Open Sources JSON').click();
  await expect(page.getByTitle('Open Sources JSON')).toContainText('sources-b.json');
  await page.keyboard.press('ControlOrMeta+z');
  await expect(page.locator('#quote-textarea')).toHaveValue('Document A original');
  await expect.poll(() => state.items.a[0].quote_original).toBe('Document A original');
});

test('keyboard access changes the sidebar width and example flag', async ({ page }) => {
  const state = useFakeDocuments(page);
  await page.goto(baseURL);
  await expect(page.getByTitle('Open Items JSON')).toContainText('items-a.json');

  const separator = page.getByRole('separator', { name: 'Resize sidebar' });
  const initialWidth = Number(await separator.getAttribute('aria-valuenow'));
  await separator.focus();
  await separator.press('ArrowRight');
  await expect(separator).toHaveAttribute('aria-valuenow', String(initialWidth + 20));

  await page.getByText('Document A original', { exact: false }).click();
  const checkbox = page.getByRole('checkbox', { name: 'Has Example' });
  await checkbox.focus();
  await checkbox.press('Space');
  await expect(checkbox).toBeChecked();
  await expect.poll(() => state.items.a[0].contains_example).toBe(true);
});

test('research documents accept numeric hierarchy numbers', async ({ page }) => {
  const state = useFakeDocuments(page);
  state.items.a = [
    {
      ...state.items.a[0],
      category_part_name: ['Origins'],
      category_part_number: [1],
      subpart_name: ['Early planning'],
      subpart_number: [1],
    },
    {
      id_item: 'item-a-2',
      quote_original: 'Document A second item',
      contains_example: false,
      category_part_name: ['Expansion'],
      category_part_number: [2],
      subpart_name: ['Rail connection'],
      subpart_number: [1],
    },
  ];

  await page.goto(baseURL);

  await expect(page.getByText('Document A original', { exact: false })).toBeVisible();
  await expect(page.getByText('Origins', { exact: true })).toBeVisible();
});

test('parser saves beside the selected reports without a native save dialog', async ({ page }) => {
  const state = useFakeDocuments(page);
  await page.goto(baseURL);

  await page.getByRole('button', { name: 'Parser', exact: true }).click();
  await page.getByRole('button', { name: 'Select Folder (Bulk)' }).click();
  await expect(page.getByText('/reports/1946_Operation_Highjump', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Save to New File' }).click();

  await expect(page.getByText('Saved scribity_items.json and scribity_sources.json', { exact: true })).toBeVisible();
  expect(state.importSaves).toHaveLength(1);
  expect(state.importSaves[0].selected_path).toBe('/reports/1946_Operation_Highjump');
  expect(state.items.a[0].id_item).toBe('imported-item');
  expect(state.sources.a[0].id_source).toBe('imported-source');
});

test('Draft restores support nesting and keeps its card controls visible', async ({ page }) => {
  const state = useFakeDocuments(page);
  state.items.a = [
    {
      id_item: 'draft-parent',
      id_script: 1,
      quote_original: 'Primary draft claim',
      rule_name: ['Topic'],
      rule_number: ['1'],
      subpart_name: [''],
      subpart_number: [''],
      id_subpart: [1],
    },
    {
      id_item: 'draft-child',
      id_script: 2,
      quote_original: 'Supporting draft evidence',
      rule_name: ['Topic'],
      rule_number: ['1'],
      subpart_name: [''],
      subpart_number: [''],
      id_subpart: [2],
    },
  ];

  await page.goto(baseURL);
  await page.getByRole('button', { name: 'Draft', exact: true }).click();

  const edit = page.getByRole('button', { name: 'Edit Primary draft claim' });
  const remove = page.getByRole('button', { name: 'Remove Primary draft claim from Draft' });
  await expect(edit).toHaveCSS('opacity', '1');
  await expect(remove).toHaveCSS('opacity', '1');

  await page.getByRole('button', { name: 'Support Primary draft claim in Draft' }).click();
  await page.getByTestId('draft-card-draft-child').dragTo(page.getByTestId('draft-card-draft-parent'));

  await expect(page.getByTestId('draft-support-draft-child')).toContainText('Supporting draft evidence');
  await expect.poll(() => state.items.a.find(item => item.id_item === 'draft-child')?.nested_under).toBe('draft-parent');
  expect(state.items.a.find(item => item.id_item === 'draft-child')?.id_script).toBe(0);

  await page.getByRole('button', { name: 'Remove Supporting draft evidence from support group' }).click();
  await expect.poll(() => state.items.a.find(item => item.id_item === 'draft-child')?.nested_under).toBe('');
});

test('Stage supports nesting and un-nesting items under a staged parent', async ({ page }) => {
  const state = useFakeDocuments(page);
  state.items.a = [
    {
      id_item: 'stage-parent',
      id_script: 1,
      quote_original: 'Primary stage claim',
      rule_name: ['Topic'],
      rule_number: ['1'],
      subpart_name: [''],
      subpart_number: [''],
      id_subpart: [1],
    },
    {
      id_item: 'stage-child',
      id_script: 0,
      quote_original: 'Supporting stage evidence',
      rule_name: ['Topic'],
      rule_number: ['1'],
      subpart_name: [''],
      subpart_number: [''],
      id_subpart: [2],
    },
  ];

  await page.goto(baseURL);
  await page.getByText('Topic', { exact: true }).first().click();

  await page.getByRole('button', { name: 'Support Primary stage claim in Stage' }).click();
  await page.getByTestId('stage-card-stage-child').dragTo(page.getByTestId('stage-card-stage-parent'));

  await expect(page.getByTestId('stage-support-stage-child')).toContainText('Supporting stage evidence');
  await expect.poll(() => state.items.a.find(item => item.id_item === 'stage-child')?.nested_under).toBe('stage-parent');

  await page.getByRole('button', { name: 'Remove Supporting stage evidence from support group' }).click();
  await expect.poll(() => state.items.a.find(item => item.id_item === 'stage-child')?.nested_under).toBe('');
  await expect(page.getByTestId('stage-card-stage-child')).toBeVisible();
});

test('sidebar count controls meet minimum text and target sizes', async ({ page }) => {
  const state = useFakeDocuments(page);
  state.items.a = [{
    ...state.items.a[0],
    rule_name: ['Accessibility'],
    rule_number: ['01'],
    subpart_name: ['Targets'],
    subpart_number: ['01'],
    id_subpart: [1],
  }];

  await page.goto(baseURL);

  const countButton = page.getByTitle(/general items \(Library\)/).first();
  await expect(countButton).toBeVisible();
  const metrics = await countButton.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return {
      fontSize: Number.parseFloat(getComputedStyle(element).fontSize),
      width: bounds.width,
      height: bounds.height,
    };
  });

  expect(metrics.fontSize).toBeGreaterThanOrEqual(12);
  expect(metrics.width).toBeGreaterThanOrEqual(28);
  expect(metrics.height).toBeGreaterThanOrEqual(28);
});

test('keyboard focus has a visible outline', async ({ page }) => {
  useFakeDocuments(page);
  await page.goto(baseURL);

  const search = page.getByPlaceholder('Search all fields...');
  await search.focus();
  const focusStyle = await search.evaluate(element => {
    const style = getComputedStyle(element);
    return {
      outlineColor: style.outlineColor,
      outlineStyle: style.outlineStyle,
      outlineWidth: Number.parseFloat(style.outlineWidth),
    };
  });

  expect(focusStyle.outlineColor).not.toBe('rgba(0, 0, 0, 0)');
  expect(focusStyle.outlineStyle).not.toBe('none');
  expect(focusStyle.outlineWidth).toBeGreaterThanOrEqual(2);
});

test('keyboard focus reveals the library card delete action', async ({ page }) => {
  useFakeDocuments(page);
  await page.goto(baseURL);

  const deleteButton = page.getByRole('button', { name: 'DELETE', exact: true });
  await deleteButton.focus();

  await expect(deleteButton).toHaveCSS('opacity', '1');
});

test('delete confirmation is a keyboard-contained dialog and restores focus', async ({ page }) => {
  useFakeDocuments(page);
  await page.goto(baseURL);

  const deleteButton = page.getByRole('button', { name: 'DELETE', exact: true });
  await deleteButton.focus();
  await deleteButton.click();

  const dialog = page.getByRole('dialog', { name: 'Delete item?' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute('aria-modal', 'true');
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused();

  const suppressCheckbox = page.getByRole('checkbox', { name: /don't ask to confirm deletes/i });
  await suppressCheckbox.focus();
  await page.keyboard.press('Shift+Tab');
  await expect(page.getByRole('button', { name: 'Delete Item' })).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(deleteButton).toBeFocused();
});

test('new document dialog closes with Escape and returns focus to its persistent trigger', async ({ page }) => {
  useFakeDocuments(page);
  await page.goto(baseURL);

  const createButton = page.getByTitle('Create new...');
  await createButton.click();
  await page.getByRole('button', { name: 'New Document' }).click();

  const dialog = page.getByRole('dialog', { name: 'New Document' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute('aria-modal', 'true');
  await expect(page.getByRole('button', { name: /Book Mode/ })).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(createButton).toBeFocused();
});

test('generated form fields are associated with their visible labels', async ({ page }) => {
  const state = useFakeDocuments(page);
  state.items.a[0] = {
    ...state.items.a[0],
    rule_name: ['Accessibility'],
    rule_number: ['13'],
    subpart_name: ['Semantics'],
    subpart_number: ['1'],
    user_01_comments: 'Keyboard review',
  };
  await page.goto(baseURL);
  await page.getByText('Document A original', { exact: false }).click();

  await expect(page.getByLabel('Rule', { exact: true })).toHaveValue('Accessibility');
  await page.getByRole('button', { name: /Additional Information/ }).click();
  await expect(page.getByLabel('user 01 comments', { exact: true })).toHaveValue('Keyboard review');
});

test('save status is exposed as a polite live region', async ({ page }) => {
  useFakeDocuments(page);
  await page.goto(baseURL);

  const status = page.getByRole('status');
  await expect(status).toHaveAttribute('aria-live', 'polite');
  await openAAndEdit(page);
  await expect(status).toHaveText('Saved');
});

test('icon-only controls have explicit accessible names', async ({ page }) => {
  const state = useFakeDocuments(page);
  state.items.a[0] = {
    ...state.items.a[0],
    rule_name: ['Accessibility', 'Extra'],
    rule_number: ['13', '14'],
    subpart_name: ['Semantics', ''],
    subpart_number: ['1', ''],
    id_subpart: [1, 0],
  };
  await page.goto(baseURL);
  await page.getByText('Document A original', { exact: false }).click();

  await expect(page.getByRole('button', { name: 'Delete rule row 1' })).toHaveCount(0);
  const removeRule = page.getByRole('button', { name: 'Delete rule row 2' });
  await expect(removeRule).toBeVisible();
  await expect(removeRule).toHaveCSS('opacity', '1');
  await expect(removeRule.locator('svg')).toBeVisible();
  await page.getByTitle('Show Stage').click();
  await expect(page.getByRole('button', { name: 'Close Stage' })).toBeVisible();
});

// Content and chrome must survive a missing icon library, including disabled
// controls. Deliberately keep the pointer away from the cards.
test('Stage and Draft actions render readable buttons without Lucide', async ({ page }) => {
  await page.route('**/lucide@latest', route => route.fulfill({
    contentType: 'application/javascript', body: 'window.lucide = undefined;',
  }));
  const state = useFakeDocuments(page);
  state.items.a = [1, 2].map(n => ({
    id_item: `visible-${n}`, id_script: n, quote_original: `Visible claim ${n}`,
    rule_name: ['Topic'], rule_number: ['1'], subpart_name: [''],
    subpart_number: [''], id_subpart: [n],
  }));
  await page.goto(baseURL);
  await page.getByText('Topic', { exact: true }).first().click();
  const resizer = page.getByRole('separator', { name: 'Resize stage' });
  await resizer.focus();
  await page.keyboard.press('Home'); // Narrowest supported Stage panel.
  await page.mouse.move(0, 0);

  async function checkButtons(card, labels) {
    for (const label of labels) {
      const titles = { Edit: 'Edit in Inspector', Support: 'Support: click, then drag an item onto this card', '↑ Up': 'Move up', '↓ Down': 'Move down', Remove: 'Remove from Draft' };
      const button = card.getByTitle(titles[label], { exact: true });
      await expect(button).toBeVisible();
      if (label === 'Remove') {
        await expect(button).toHaveText(label);
      } else {
        await expect(button).toHaveText('');
        await expect(button.locator('svg')).toBeVisible();
      }
      const appearance = await button.evaluate(el => {
        const css = getComputedStyle(el);
        const box = el.getBoundingClientRect();
        const cardBox = el.closest('[data-testid]').getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(el);
        const svg = el.querySelector('svg');
        const textBox = svg ? svg.getBoundingClientRect() : range.getBoundingClientRect();
        const ink = svg ? svg.getBBox() : textBox;
        const graphicStyle = svg ? getComputedStyle(svg) : css;
        const rgb = color => color.match(/[\d.]+/g).slice(0, 3).map(Number);
        const luminance = color => rgb(color).map(n => {
          const s = n / 255;
          return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
        }).reduce((sum, n, i) => sum + n * [0.2126, 0.7152, 0.0722][i], 0);
        const fg = luminance(css.color), bg = luminance(css.backgroundColor);
        return {
          width: box.width, height: box.height, textWidth: textBox.width,
          textHeight: textBox.height, inkWidth: ink.width, inkHeight: ink.height,
          stroke: graphicStyle.stroke, strokeWidth: parseFloat(graphicStyle.strokeWidth),
          isIcon: Boolean(svg), fontSize: parseFloat(css.fontSize),
          background: css.backgroundColor, borderWidth: parseFloat(css.borderTopWidth),
          borderStyle: css.borderTopStyle, borderColor: css.borderTopColor,
          contrast: (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05),
          insideCard: box.left >= cardBox.left && box.right <= cardBox.right,
        };
      });
      expect(appearance.width).toBeGreaterThanOrEqual(32);
      expect(appearance.height).toBeGreaterThanOrEqual(32);
      expect(appearance.textWidth).toBeGreaterThan(10);
      expect(appearance.textHeight).toBeGreaterThan(8);
      expect(appearance.inkWidth).toBeGreaterThan(8);
      expect(appearance.inkHeight).toBeGreaterThan(8);
      if (appearance.isIcon) {
        expect(appearance.stroke).not.toBe('none');
        expect(appearance.stroke).not.toBe('rgba(0, 0, 0, 0)');
        expect(appearance.strokeWidth).toBeGreaterThanOrEqual(2);
      }
      expect(appearance.fontSize).toBeGreaterThanOrEqual(12);
      expect(appearance.background).not.toBe('rgba(0, 0, 0, 0)');
      expect(appearance.borderWidth).toBeGreaterThanOrEqual(1);
      expect(appearance.borderStyle).not.toBe('none');
      expect(appearance.borderColor).not.toBe(appearance.background);
      expect(appearance.contrast).toBeGreaterThanOrEqual(4.5);
      expect(appearance.insideCard).toBe(true);
    }
  }

  for (const n of [1, 2]) {
    await checkButtons(page.getByTestId(`stage-card-visible-${n}`), ['Edit', 'Support', '↑ Up', '↓ Down']);
  }
  await page.getByRole('button', { name: 'Support Visible claim 1 in Stage' }).click();
  await page.mouse.move(0, 0);
  await checkButtons(page.getByTestId('stage-card-visible-1'), ['Support']);
  await page.getByRole('button', { name: 'Draft', exact: true }).click();
  await page.mouse.move(0, 0);
  await checkButtons(page.getByTestId('draft-card-visible-1'), ['Edit', 'Support', 'Remove']);
});
