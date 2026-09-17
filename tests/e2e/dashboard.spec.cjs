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
