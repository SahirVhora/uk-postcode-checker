/* Separate browsing contexts keep chart IDs, requests and errors independent. */
const comparisonCategories = new Set(['location', 'crime', 'schools', 'transport', 'tenure', 'ethnicity', 'religion', 'planning']);
function comparisonPostcode(raw) {
  const compact = raw.replace(/\s+/g, '').toUpperCase();
  if (!/^(GIR0AA|[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2})$/.test(compact)) return null;
  return `${compact.slice(0, -3)} ${compact.slice(-3)}`;
}
function comparisonStyle(category) {
  const selected = comparisonCategories.has(category) ? [category] : [...comparisonCategories];
  const selectors = selected.map(key => `#results > #card-${key}`).join(', ');
  return `body > header, body > div:not(#results), #footer { display: none !important; }
    body { min-height: 0; }
    #results.visible { display: block; padding: 0; margin: 0; max-width: none; }
    #results > .card { display: none !important; }
    ${selectors} { display: block !important; margin: 0; border: 0; border-bottom: 1px solid #d5dde5; box-shadow: none; border-radius: 0; }`;
}
function initComparison() {
  const byId = id => document.getElementById(id);
  const frames = [byId('first-profile'), byId('second-profile')];
  let pendingLayout;
  const observers = new Map();
  function scheduleLayout() {
    cancelAnimationFrame(pendingLayout);
    pendingLayout = requestAnimationFrame(() => {
      // Match each row's height so both postcodes stay aligned as data arrives.
      for (const category of comparisonCategories) {
        const cards = frames.map(frame => frame.contentDocument?.getElementById(`card-${category}`));
        cards.forEach(card => { if (card) card.style.minHeight = '0'; });
        const height = Math.max(...cards.map(card => card?.getBoundingClientRect().height || 0));
        cards.forEach(card => { if (card) card.style.minHeight = `${height}px`; });
      }
      for (const frame of frames) {
        const results = frame.contentDocument?.getElementById('results');
        if (results) frame.style.height = `${Math.ceil(results.getBoundingClientRect().height) + 2}px`;
      }
    });
  }
  function updateCategory() {
    for (const frame of frames) {
      const doc = frame.contentDocument;
      if (!doc?.head) continue;
      let style = doc.getElementById('comparison-style');
      if (!style) {
        style = doc.createElement('style');
        style.id = 'comparison-style';
        doc.head.appendChild(style);
      }
      style.textContent = comparisonStyle(byId('category').value);
    }
    scheduleLayout();
  }
  frames.forEach(frame => frame.addEventListener('load', () => {
    observers.get(frame)?.disconnect();
    const results = frame.contentDocument?.getElementById('results');
    if (results) {
      const observer = new MutationObserver(scheduleLayout);
      observer.observe(results, { childList: true, subtree: true, characterData: true });
      observers.set(frame, observer);
    }
    updateCategory();
  }));
  window.addEventListener('resize', scheduleLayout);
  byId('category').addEventListener('change', updateCategory);
  byId('compare-form').addEventListener('submit', event => {
    event.preventDefault();
    const postcodes = ['first', 'second'].map(id => comparisonPostcode(byId(id).value));
    if (postcodes.includes(null)) {
      byId('errors').textContent = 'Enter two valid UK postcodes, for example B90 3DF and SW1A 1AA.';
      return;
    }
    if (postcodes[0] === postcodes[1]) {
      byId('errors').textContent = 'Enter two different postcodes to compare.';
      return;
    }
    byId('errors').textContent = '';
    byId('comparison').hidden = false;
    postcodes.forEach((postcode, i) => {
      const side = i === 0 ? 'first' : 'second';
      byId(side).value = postcode;
      byId(`${side}-heading`).textContent = postcode;
      frames[i].title = `${postcode} postcode profile`;
      frames[i].src = `index.html?postcode=${encodeURIComponent(postcode)}`;
    });
  });
}
if (typeof document !== 'undefined') initComparison();
