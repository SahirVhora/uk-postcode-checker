import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
const source = await readFile(new URL('../compare.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source, context);
test('comparison normalises input and rejects invalid postcodes', () => {
  for (const [raw, expected] of [[' b903df ', 'B90 3DF'], ['sw1a 1aa', 'SW1A 1AA'], ['GIR 0AA', 'GIR 0AA'], ['', null], ['London', null], ['<script>', null]]) {
    assert.equal(context.comparisonPostcode(raw), expected);
  }
});
test('comparison shows only the selected category and rejects arbitrary CSS selectors', () => {
  assert.match(context.comparisonStyle('crime'), /#card-crime \{ display: block/);
  assert.equal(context.comparisonStyle('invalid'), context.comparisonStyle('all'));
  for (const category of ['location', 'crime', 'schools', 'transport', 'tenure', 'ethnicity', 'religion', 'planning']) {
    assert.ok(context.comparisonStyle('all').includes(`#card-${category}`));
  }
});
test('comparison validates both inputs before loading isolated profiles', () => {
  const elements = {};
  for (const id of ['first', 'second', 'errors', 'comparison', 'category', 'compare-form', 'first-profile', 'second-profile', 'first-heading', 'second-heading']) {
    elements[id] = { value: '', events: {}, addEventListener(event, fn) { this.events[event] = fn; } };
  }
  const browser = vm.createContext({ window: { addEventListener() {} }, document: { getElementById: id => elements[id] } });
  vm.runInContext(source, browser);
  const submit = () => elements['compare-form'].events.submit({ preventDefault() {} });
  elements.first.value = 'b903df'; elements.second.value = 'invalid'; submit();
  assert.equal(elements['first-profile'].src, undefined);
  elements.second.value = 'B90 3DF'; submit();
  assert.match(elements.errors.textContent, /different/);
  elements.second.value = 'SW1A1AA'; submit();
  assert.equal(elements['first-profile'].src, 'index.html?postcode=B90%203DF');
  assert.equal(elements['second-profile'].src, 'index.html?postcode=SW1A%201AA');
  assert.equal(elements.comparison.hidden, false);
  assert.equal(elements.errors.textContent, '');
});
