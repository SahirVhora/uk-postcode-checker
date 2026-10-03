import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const appUrl = new URL('../index.html', import.meta.url);
const fixtureUrl = path => new URL(`./fixtures/${path}`, import.meta.url);

function extractFunctionBlock(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.notEqual(start, -1, `missing ${startMarker}`);
  assert.notEqual(end, -1, `missing ${endMarker}`);
  return source.slice(start, end);
}

/** Minimal DOM element good enough for setCardContent and the score controls. */
function makeElement(id, html = '') {
  return {
    id,
    hidden: true,
    innerHTML: html,
    textContent: '',
    value: '',
    style: {},
    listeners: {},
    addEventListener(type, listener) { this.listeners[type] = listener; },
    querySelector(selector) { return selector === 'h2' ? { cloneNode: () => ({ outerHTML: `<h2>${id}</h2>` }) } : null; },
    appendChild(child) { this.innerHTML += child.outerHTML; },
    insertAdjacentHTML(_where, more) { this.innerHTML += more; },
  };
}

async function loadAreaPack({ files = {} } = {}) {
  const source = await readFile(appUrl, 'utf8');
  const helpers = extractFunctionBlock(source, 'function escapeHtml', '/**\n   * Wrap long text labels');
  const setCard = extractFunctionBlock(source, 'function setCardContent', '/**\n   * Calculate distance');
  const areaPack = extractFunctionBlock(source, '// AREA PACK START', '// AREA PACK END');
  const elements = {};
  const requested = [];
  const document = {
    getElementById(id) {
      if (!elements[id]) {
        elements[id] = makeElement(id);
        // Like a browser, take the initial value from the rendered markup.
        const markup = Object.values(elements).map(el => el.innerHTML).join('');
        const match = markup.match(new RegExp(`id="${id}"[^>]*value="([^"]*)"`));
        if (match) elements[id].value = match[1];
      }
      return elements[id];
    },
  };
  const context = {
    URL,
    console,
    document,
    searchAbortController: new AbortController(),
    fetchWithTimeout: async url => {
      requested.push(String(url));
      const body = files[String(url)];
      if (body === undefined) return { ok: false, status: 404, json: async () => null };
      return { ok: true, status: 200, json: async () => JSON.parse(body) };
    },
  };
  vm.runInNewContext(
    `${helpers}\n${setCard}\n${areaPack}\nglobalThis.api = { renderAreaPack, areaTotalScore, areaPriceWithBudget, hideAreaPackCards };`,
    context,
  );
  return { source, elements, requested, ...context.api };
}

async function packFiles() {
  const read = path => readFile(fixtureUrl(`area-pack/${path}`), 'utf8');
  return {
    'data/area-pack/index.json': await read('index.json'),
    'data/area-pack/postcodes/B90-3D.json': await read('postcodes/B90-3D.json'),
    'data/area-pack/sectors/B90-3.json': await read('sectors/B90-3.json'),
  };
}

test('browser score formula matches the Python formula on shared cases', async () => {
  const { areaTotalScore, areaPriceWithBudget } = await loadAreaPack();
  const parity = JSON.parse(await readFile(fixtureUrl('score_parity.json'), 'utf8'));
  for (const c of parity.cases) assert.equal(areaTotalScore(c.subs, c.weights), c.expected);
  for (const c of parity.budget_cases) {
    assert.equal(areaPriceWithBudget(c.raw, c.budget_value, c.budget, c.multiplier), c.expected);
  }
});

test('new cards render from fixture JSON for a pack postcode', async () => {
  const { renderAreaPack, elements } = await loadAreaPack({ files: await packFiles() });
  assert.equal(await renderAreaPack('B90 3DF'), true);

  for (const id of ['card-admissions', 'card-prices', 'card-score']) assert.equal(elements[id].hidden, false);
  const admissions = elements['card-admissions'].innerHTML;
  assert.match(admissions, /Alderbrook School/);
  assert.match(admissions, /In catchment/);
  assert.match(admissions, /historically safe/);
  assert.match(admissions, /Tudor Grange Academy Solihull/);
  assert.match(admissions, /gate point unverified/);
  assert.match(admissions, /postcode-centroid estimate/);
  assert.match(admissions, /Catchments as of/);

  const prices = elements['card-prices'].innerHTML;
  assert.match(prices, /Land Registry as of/);
  assert.match(prices, /£365,000/);
  assert.match(prices, /House numbers are not shown/);

  assert.equal(elements['area-total'].textContent, '62');
  assert.equal(elements['area-pack-attribution'].hidden, false);
  assert.match(elements['area-pack-attribution'].innerHTML, /HM Land Registry/);
  assert.match(elements['area-pack-attribution'].innerHTML, /OpenStreetMap contributors/);
});

test('weight sliders and budget recompute the total live', async () => {
  const { renderAreaPack, elements } = await loadAreaPack({ files: await packFiles() });
  await renderAreaPack('B90 3DF');
  for (const key of ['price', 'safety', 'community']) elements[`area-w-${key}`].value = '0';
  elements['area-w-school'].value = '100';
  elements['area-w-school'].listeners.input();
  assert.equal(elements['area-total'].textContent, '70');

  elements['area-w-school'].value = '0';
  elements['area-w-price'].value = '100';
  elements['area-budget'].value = '300000'; // below the area's family-home price: hard penalty
  elements['area-budget'].listeners.input();
  assert.equal(elements['area-val-price'].textContent, '15');
});

test('non-pack postcodes leave the page exactly as before', async () => {
  const { renderAreaPack, elements, requested } = await loadAreaPack({ files: await packFiles() });
  assert.equal(await renderAreaPack('SW1A 1AA'), false);
  assert.deepEqual(requested, ['data/area-pack/index.json']);
  for (const id of ['card-admissions', 'card-prices', 'card-score']) {
    assert.equal(elements[id]?.hidden ?? true, true);
    assert.equal(elements[id]?.innerHTML ?? '', '');
  }
});

test('a missing pack (for example file:// or not exported) fails silently', async () => {
  const { renderAreaPack } = await loadAreaPack({ files: {} });
  assert.equal(await renderAreaPack('B90 3DF'), false);
});

test('index.html keeps the original cards and only adds hidden pack cards', async () => {
  const source = await readFile(appUrl, 'utf8');
  assert.match(source, /const cards = \['card-location','card-crime','card-ethnicity','card-tenure','card-schools','card-religion','card-planning','card-transport'\];/);
  for (const id of ['card-admissions', 'card-prices', 'card-score']) {
    assert.match(source, new RegExp(`id="${id}" hidden`));
  }
  assert.match(source, /hideAreaPackCards\(\);/);
  assert.match(source, /renderAreaPack\(r\.postcode\)/);
  assert.doesNotMatch(source, /\u2014/, 'no em dashes');
});
