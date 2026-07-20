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

test('stalled fetches are aborted by the production timeout helper', async () => {
  const source = await readFile(appUrl, 'utf8');
  assert.doesNotMatch(source, /fetch\([^\n]*\{[^}]*\btimeout\s*:/, 'fetch timeout options are ignored by browsers');

  const helpers = extractFunctionBlock(source, 'function combineAbortSignals', 'const normalisePostcode');
  const context = {
    AbortController,
    AbortSignal,
    DOMException,
    clearTimeout,
    setTimeout,
    fetch: (_url, { signal }) => new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    }),
  };
  vm.runInNewContext(`${helpers}; globalThis.fetchWithTimeout = fetchWithTimeout;`, context);

  await assert.rejects(
    context.fetchWithTimeout('https://example.test/stalled', {}, 10),
    (error) => error.name === 'AbortError' || error.name === 'TimeoutError',
  );
});
