import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const appUrl = new URL('../index.html', import.meta.url);

function extractFunctionBlock(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.notEqual(start, -1, `missing ${startMarker}`);
  assert.notEqual(end, -1, `missing ${endMarker}`);
  return source.slice(start, end);
}

async function loadPlanningHelpers() {
  const source = await readFile(appUrl, 'utf8');
  const helpers = extractFunctionBlock(source, 'function escapeHtml', '/**\n   * Wrap long text labels');
  const context = { URL };
  vm.runInNewContext(
    `${helpers}; globalThis.helpers = { escapeHtml, safeExternalUrl, planningExtensionKind, formatPlanningDate };`,
    context,
  );
  return { source, ...context.helpers };
}

test('planning card is wired into the postcode search', async () => {
  const { source } = await loadPlanningHelpers();
  assert.match(source, /id="card-planning"/);
  assert.match(source, /renderPlanningExtensions\(lat, lng\)/);
  assert.match(source, /https:\/\/www\.planit\.org\.uk\/api\/applics\/json/);
  assert.match(source, /sort: 'start_date\.desc\.nullslast'/);
  assert.match(source, /planningCache\.set/);
});

test('extension classifier includes common household works', async () => {
  const { planningExtensionKind } = await loadPlanningHelpers();
  assert.equal(planningExtensionKind({ description: 'Single-storey rear extension' }), 'Extension');
  assert.equal(planningExtensionKind({ description: 'Loft conversion with rear dormer' }), 'Loft / dormer');
  assert.equal(planningExtensionKind({ description: 'Conversion of the existing garage', other_fields: { application_type: 'Garage conversion' } }), 'Garage conversion');
  assert.equal(planningExtensionKind({ description: 'New front porch' }), 'Porch');
});

test('extension classifier excludes administrative follow-ups and unrelated work', async () => {
  const { planningExtensionKind } = await loadPlanningHelpers();
  assert.equal(planningExtensionKind({ description: 'Discharge of condition for an approved rear extension' }), '');
  assert.equal(planningExtensionKind({ description: 'Variation of condition for an existing extension' }), '');
  assert.equal(planningExtensionKind({ description: 'Fell one ash tree' }), '');
});

test('planning output helpers escape API text and reject unsafe links', async () => {
  const { escapeHtml, safeExternalUrl, formatPlanningDate } = await loadPlanningHelpers();
  assert.equal(escapeHtml('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  assert.equal(safeExternalUrl('javascript:alert(1)'), '#');
  assert.equal(safeExternalUrl('https://example.test/record?id=1&tab=docs'), 'https://example.test/record?id=1&amp;tab=docs');
  assert.equal(formatPlanningDate('2026-01-15'), '15 Jan 2026');
  assert.equal(formatPlanningDate('unknown'), 'Date unavailable');
});

test('planning renderer queries newest records and safely renders matches', async () => {
  const source = await readFile(appUrl, 'utf8');
  const helpers = extractFunctionBlock(source, 'function escapeHtml', '/**\n   * Wrap long text labels');
  const renderer = extractFunctionBlock(
    source,
    'async function renderPlanningExtensions',
    '/**\n   * Fetch and render nearby transport',
  );
  let requestedUrl = '';
  let rendered = {};
  const context = {
    AbortController,
    URL,
    URLSearchParams,
    console,
    fetchWithTimeout: async url => {
      requestedUrl = String(url);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          records: [
            {
              uid: 'SAFE/1',
              start_date: '2026-02-03',
              address: '<img src=x onerror=alert(1)>',
              description: 'Single-storey rear extension',
              location: { coordinates: [-1.8, 52.4] },
              link: 'https://example.test/application/1',
              app_state: 'Undecided',
              other_fields: {},
            },
            {
              uid: 'EXCLUDED/2',
              start_date: '2026-02-04',
              address: '2 Example Road',
              description: 'Discharge of condition for a rear extension',
              location: { coordinates: [-1.8, 52.4] },
              link: 'https://example.test/application/2',
              app_state: 'Permitted',
              other_fields: {},
            },
          ],
        }),
      };
    },
    setCardContent: (id, html) => { rendered = { id, html }; },
    distKm: () => 0.42,
  };
  vm.runInNewContext(
    `
      const SEARCH_RADIUS = { planning: 1000 };
      const PLANNING_LOOKBACK_DAYS = 1826;
      const PLANNING_MAX_RECORDS = 100;
      const PLANNING_CACHE_MS = 60000;
      const API_TIMEOUTS = { planning: 15000 };
      const planningCache = new Map();
      const searchAbortController = new AbortController();
      ${helpers}
      ${renderer}
      globalThis.renderPlanningExtensions = renderPlanningExtensions;
    `,
    context,
  );

  await context.renderPlanningExtensions(52.4, -1.8);

  const params = new URL(requestedUrl).searchParams;
  assert.equal(params.get('sort'), 'start_date.desc.nullslast');
  assert.equal(params.get('krad'), '1');
  assert.equal(params.get('recent'), '1826');
  assert.equal(rendered.id, 'card-planning');
  assert.match(rendered.html, /SAFE\/1/);
  assert.doesNotMatch(rendered.html, /EXCLUDED\/2/);
  assert.match(rendered.html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(rendered.html, /<img src=x/);
});
