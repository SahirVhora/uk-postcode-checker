import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const pageUrl = new URL('../shortlist.html', import.meta.url);
const fixtureUrl = path => new URL(`./fixtures/${path}`, import.meta.url);

function extractFunctionBlock(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.notEqual(start, -1, `missing ${startMarker}`);
  assert.notEqual(end, -1, `missing ${endMarker}`);
  return source.slice(start, end);
}

async function loadShortlist() {
  const source = await readFile(pageUrl, 'utf8');
  const block = extractFunctionBlock(source, '// SHORTLIST START', '// SHORTLIST END');
  const context = {};
  vm.runInNewContext(
    `${block}\nglobalThis.api = { areaTotalScore, areaPriceWithBudget, rowsFromPack, scoreRows, filterRows, sortRows, toCsv, scoreColour, COLUMNS };`,
    context,
  );
  return { source, ...context.api };
}

test('shortlist score formula matches the shared parity cases', async () => {
  const { areaTotalScore, areaPriceWithBudget } = await loadShortlist();
  const parity = JSON.parse(await readFile(fixtureUrl('score_parity.json'), 'utf8'));
  for (const c of parity.cases) assert.equal(areaTotalScore(c.subs, c.weights), c.expected);
  for (const c of parity.budget_cases) assert.equal(areaPriceWithBudget(c.raw, c.budget_value, c.budget, c.multiplier), c.expected);
});

test('pack rows are scored, filtered and ranked', async () => {
  const { rowsFromPack, scoreRows, filterRows, sortRows } = await loadShortlist();
  const pack = JSON.parse(await readFile(fixtureUrl('area-pack/shortlist.json'), 'utf8'));
  const rows = rowsFromPack(pack);
  assert.equal(rows.length, 6);
  assert.ok('pcds' in rows[0] && 'total' in rows[0]);

  const scored = scoreRows(rows, pack.scoring.weights, pack.scoring.budget_gbp, pack.scoring.over_budget_multiplier);
  // With default weights and budget the browser total equals the pipeline total.
  for (const r of scored) assert.equal(r.total_now, r.total);

  const ranked = sortRows(scored, 'total_now', 'descending');
  assert.deepEqual(ranked.map(r => r.rank), [1, 2, 3, 4, 5, 6]);
  const byPostcode = sortRows(scored, 'pcds', 'ascending');
  assert.ok(byPostcode[0].pcds <= byPostcode[1].pcds);

  assert.equal(filterRows(scored, { catchment: 'either' }).every(r => r.in_target), true);
  assert.equal(filterRows(scored, { minScore: 101 }).length, 0);
  assert.equal(filterRows(scored, { outcode: 'B99' }).length, 0);
  const cheap = filterRows(scored, { budget: 1 });
  assert.equal(cheap.every(r => r.budget_value === null || r.budget_value === undefined), true);
});

test('sorting keeps missing values last', async () => {
  const { sortRows } = await loadShortlist();
  const rows = [{ pcds: 'A', total_now: null, v: null }, { pcds: 'B', total_now: 50, v: 2 }, { pcds: 'C', total_now: 70, v: 1 }];
  assert.deepEqual(sortRows(rows, 'v', 'ascending').map(r => r.pcds), ['C', 'B', 'A']);
  assert.deepEqual(sortRows(rows, 'v', 'descending').map(r => r.pcds), ['B', 'C', 'A']);
  assert.equal(sortRows(rows, 'v', 'ascending').find(r => r.pcds === 'C').rank, 1);
});

test('CSV export quotes values and blocks spreadsheet formulas', async () => {
  const { toCsv } = await loadShortlist();
  const csv = toCsv([{ a: 'B90 3DF', b: 'x, "y"', c: '=HYPERLINK("bad")', d: null, e: -1.5 }],
    [{ key: 'a', label: 'Postcode' }, { key: 'b', label: 'Text' }, { key: 'c', label: 'Formula' }, { key: 'd', label: 'Empty' }, { key: 'e', label: 'Num' }]);
  assert.equal(csv, 'Postcode,Text,Formula,Empty,Num\nB90 3DF,"x, ""y""","\'=HYPERLINK(""bad"")",,-1.5\n');
});

test('map colours cover every score and the page publishes no polygons', async () => {
  const { scoreColour, source } = await loadShortlist();
  for (const v of [0, 34.9, 35, 64, 79.9, 80, 100]) assert.match(scoreColour(v), /^#[0-9a-f]{6}$/);
  assert.equal(scoreColour(null), '#bdbdbd');
  assert.match(source, /cdnjs\.cloudflare\.com\/ajax\/libs\/leaflet\/1\.9\.4\/leaflet\.min\.js" integrity="sha512-/);
  assert.doesNotMatch(source, /L\.(polygon|geoJSON|geoJson)\(/);
  assert.doesNotMatch(source, /\u2014/, 'no em dashes');
});
