# CODE REVIEW: UK Postcode Checker

**Reviewer:** Senior Web Developer  
**Date:** March 24, 2026  
**Overall Assessment:** Good foundation, but needs improvements in error handling, accessibility, performance, and maintainability.

---

## 🔴 CRITICAL ISSUES

### 1. **Unused Google Places API Configuration**
- **Location:** Line 177 (`const GOOGLE_PLACES_KEY = "";`)
- **Issue:** Variable is defined but never used. Confuses developers about its purpose.
- **Impact:** Dead code, misleading functionality
- **Fix:** Either implement the feature or document why it's disabled
- **Suggested:** Remove or implement proper Google Places integration with:
  ```js
  async function fetchGoogleRating(schoolName) {
    if (!GOOGLE_PLACES_KEY) return null;
    // Implement Places API call
  }
  ```

### 2. **No Input Validation / Sanitization**
- **Location:** Line 195 (postcode input handling)
- **Issue:** Only `maxlength="8"` exists; no format validation
- **Risk:** 
  - User could enter invalid postcodes causing failed API calls
  - No feedback on what constitutes a valid postcode
  - Potential XSS if data piped through unsanitized HTML
- **Fix:**
  ```js
  function isValidPostcode(pc) {
    // UK postcode regex: roughly 6-7 chars, alphanumeric + space/number
    const regex = /^[A-Z]{1,2}[0-9]{1,2}[A-Z]?\s?[0-9][A-Z]{2}$/i;
    return regex.test(pc.trim());
  }
  // Use before API call
  ```

### 3. **Race Condition - Multiple Simultaneous Requests**
- **Location:** Line 238-240 (`runSearch()`)
- **Issue:** If user clicks search button twice quickly, two requests run simultaneously
- **Impact:** 
  - Duplicate API calls
  - Results display in unpredictable order
  - Memory leak (charts created twice)
- **Fix:** Implement AbortController:
  ```js
  let searchAbortController = null;
  
  async function runSearch() {
    if (searchAbortController) searchAbortController.abort();
    searchAbortController = new AbortController();
    
    try {
      const pcRes = await fetch(url, { signal: searchAbortController.signal });
      // ...
    }
  }
  ```

### 4. **Inconsistent API Response Error Handling**
- **Location:** Multiple render functions (lines 300-700)
- **Issue:** 
  - No validation that API responses contain expected properties
  - Assumes nested objects exist (e.g., `r.codes?.lsoa`)
  - Silent failures with generic error messages
- **Example Problem:**
  ```js
  const lsoaCode = r.codes?.lsoa || r.codes?.lsoa21 || '';
  // If codes is undefined, this fails silently
  ```
- **Fix:** Add defensive validation:
  ```js
  function validateResponse(data, requiredFields) {
    for (const field of requiredFields) {
      if (!data[field]) throw new Error(`Missing field: ${field}`);
    }
    return data;
  }
  ```

---

## 🟡 MAJOR ISSUES

### 5. **Chart Memory Leak / Performance**
- **Location:** Lines 216-217, 267
- **Issue:** 
  - Charts destroyed and recreated on every search (even same postcode)
  - No caching mechanism
  - Chart.js instances may not fully cleanup
- **Performance Impact:** 
  - 2+ API calls per search
  - Chart.js DOM pollution
- **Fix:** 
  - Implement search result caching:
    ```js
    const searchCache = {};
    
    function getCachedResult(pc) {
      return searchCache[pc];
    }
    
    function cacheResult(pc, result) {
      searchCache[pc] = result;
      // Implement TTL (e.g., 1 hour)
    }
    ```
  - Reuse chart instances instead of destroying:
    ```js
    if (crimeChart) {
      crimeChart.data.labels = newLabels;
      crimeChart.data.datasets[0].data = newData;
      crimeChart.update();
    } else {
      crimeChart = makeBarChart(...);
    }
    ```

### 6. **Inconsistent Timeout Values**
- **Location:** Lines 363 (12s), 385 (30s), 469 (30s)
- **Issue:** Different APIs have different timeout values with no documentation
- **Risk:** 
  - Slow APIs may always timeout
  - Some requests abandoned prematurely
- **Fix:**
  ```js
  const API_TIMEOUTS = {
    postcodes_io: 8000,
    police: 10000,
    nomis: 15000,
    overpass: 30000,
  };
  ```

### 7. **Accessibility Issues**
- **Location:** Entire page
- **Missing:**
  - ARIA labels on interactive elements
  - Semantic HTML (no `<section>`, `<article>`, `<nav>`)
  - Color-blind safe charts
  - Keyboard navigation incomplete
- **Fix:**
  ```html
  <input 
    id="postcodeInput" 
    type="text" 
    placeholder="e.g. B90 2DH" 
    aria-label="Enter UK postcode"
    aria-autocomplete="none"
  />
  
  <button 
    id="searchBtn" 
    aria-busy="false"
    aria-label="Search postcode information"
  >
    Search
  </button>
  ```

### 8. **Chart Color Accessibility**
- **Location:** Lines 329-336, 412, 537, 572
- **Issue:** Colors not tested for color-blind users (red-green blindness)
- **Fix:** Use colorblind-safe palettes:
  ```js
  const COLORBLIND_PALETTE = [
    '#0173B2', '#DE8F05', '#CC78BC', '#CA9161', '#949494'
  ];
  ```

---

## 🟠 MODERATE ISSUES

### 9. **No Request Deduplication**
- **Location:** Line 248 (`Promise.allSettled`)
- **Issue:** Multiple cards fetch from same endpoints simultaneously with redundant requests
- **Example:** Multiple district/region lookups could be batched
- **Fix:** Implement request coalescing

### 10. **Vague Error Messages**
- **Location:** Lines 291, 364, 386, etc.
- **Examples:**
  - `"Crime data unavailable: ${err.message}"` - doesn't help user
  - `"Postcode not found (${pcRes.status})"` - 400 vs 404 unclear
- **Fix:**
  ```js
  const ERROR_MESSAGES = {
    INVALID_POSTCODE: 'Postcode not found. Please check the format.',
    API_TIMEOUT: 'Request took too long. Please try again.',
    RATE_LIMITED: 'Too many requests. Please wait a moment.',
    NETWORK_ERROR: 'Network error. Please check your connection.',
  };
  ```

### 11. **No Rate Limit Handling**
- **Location:** All fetch calls
- **Issue:** No detection/handling of HTTP 429 (rate limit) responses
- **Risk:** Silent failures when APIs rate limit
- **Fix:**
  ```js
  if (res.status === 429) {
    const retryAfter = res.headers.get('Retry-After');
    throw new Error(`Rate limited. Retry after ${retryAfter}s`);
  }
  ```

### 12. **Code Organization**
- **Location:** Entire file (716 lines)
- **Issue:** 
  - All code in single HTML file
  - Difficult to test individual functions
  - No separation of concerns
  - Styling mixed with HTML and JS
- **Proper Structure:**
  ```
  /index.html (markup only)
  /css/styles.css
  /js/
    ├── api.js (API calls)
    ├── render.js (UI rendering)
    ├── validation.js
    ├── charts.js
    └── main.js (controller)
  ```

### 13. **Missing Responsive Design Edge Cases**
- **Location:** Lines 75-78 (media query)
- **Issue:** Only one breakpoint at 700px; tablet sizes may have issues
- **Table Scaling:** Tables don't scroll well on small screens
- **Fix:**
  ```css
  @media (max-width: 480px) {
    table { font-size: 0.70rem; }
    thead { display: none; } /* Use card layout for small screens */
  }
  ```

### 14. **No Loading State for UI**
- **Location:** Line 238 (button disabled but minimal feedback)
- **Issue:** No indication to user that data is being fetched
  - No skeleton loaders
  - No progress indicator
  - Spinners appear instantly (jarring)
- **Fix:**
  ```js
  btn.setAttribute('aria-busy', 'true');
  btn.innerHTML = '<span class="spinner" style="width:14px;height:14px"></span> Searching…';
  ```

### 15. **Missing Data Validation at Source**
- **Location:** Lines 259-260 (location render)
- **Issue:**
  ```js
  const lsoaCode = r.codes?.lsoa || r.codes?.lsoa21 || '';
  ```
  If both are undefined, LSOA lookups fail silently later
- **Fix:** Validate early:
  ```js
  if (!lsoaCode) {
    console.warn('LSOA code unavailable for', pc);
    // Show warning in UI
  }
  ```

---

## 🔵 MINOR IMPROVEMENTS

### 16. **Hardcoded Magic Values**
- **Location:** Throughout code
- **Examples:**
  - `radiusM = 3219` (line 423) - what is 3219?
  - `around:400` (line 561) - 400 what?
  - `around:${radiusM}` vs `around:3000` inconsistency
- **Fix:**
  ```js
  const SEARCH_RADIUS = {
    schools: 3.219, // km
    busStops: 0.4,  // km
    railStations: 3, // km
  };
  ```

### 17. **No Comments for Complex Logic**
- **Location:** Lines 329-336 (chart color generation)
- **Issue:** Algorithm for color generation via hue shift not explained
- **Fix:**
  ```js
  // Generate color palette using HSL hue rotation
  // Ensures 8+ visually distinct colors
  hsl(${18 + i * 10}, 85%, ${52 + i * 3}%)
  ```

### 18. **Chart Label Wrapping Function Unclear**
- **Location:** Line 203 (`wrapLabel()`)
- **Issue:** Purpose and usage not obvious
- **Fix:** Add JSDoc:
  ```js
  /**
   * Wraps long text labels for Chart.js multi-line tick display
   * @param {string} str - Text to wrap
   * @param {number} maxLen - Max characters per line (default 22)
   * @returns {string|string[]} - Single string or array for multi-line
   */
  function wrapLabel(str, maxLen = 22) {
  ```

### 19. **No Offline Fallback**
- **Issue:** No service worker or offline capability
- **Suggestion:** Consider caching with Service Worker:
  ```js
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js');
  }
  ```

### 20. **Chart Height Hard-coded**
- **Location:** Lines 407, 448, 521, 559
- **Issue:** `height="260"` etc. not responsive to screen size
- **Fix:** Use CSS container queries or aspect-ratio:
  ```css
  canvas {
    max-width: 100%;
    aspect-ratio: 16 / 9;
  }
  ```

---

## 📋 SECURITY REVIEW

### ✅ Safe:
- No user data stored
- APIs are read-only, public data
- No authentication tokens exposed

### ⚠️ Concerns:
- innerHTML used for API data (mitigated by likely safe input, but best to use `textContent` for names)
- GOOGLE_PLACES_KEY exposed in code (needs env variable handling if implemented)
- No Content Security Policy (CSP) headers

### Recommendation:
```html
<meta http-equiv="Content-Security-Policy" content="
  default-src 'self'; 
  script-src 'self' cdnjs.cloudflare.com; 
  style-src 'self' 'unsafe-inline'; 
  img-src 'self' data: https:;
  frame-src openstreetmap.org;
">
```

---

## 📊 PERFORMANCE IMPROVEMENTS

| Issue | Current | Recommended |
|-------|---------|-------------|
| Total bundle size | ~30KB HTML | Split to ~10KB + CSS + JS |
| First search time | 3-5s | 2-3s (with caching) |
| Chart rendering | 1s+ each | 200-300ms (reuse instances) |
| API requests per search | 6-7 | 6-7 (same) but cached |
| Memory usage | Grows | Fixed (with cleanup) |

---

## 🎯 PRIORITY ACTION ITEMS

### **Phase 1 (Critical):**
1. ✅ Add input validation for postcodes
2. ✅ Implement AbortController for race conditions
3. ✅ Add proper error validation for API responses
4. ✅ Remove unused Google API key code

### **Phase 2 (High):**
5. ✅ Implement search result caching
6. ✅ Reuse chart instances instead of destroying
7. ✅ Add ARIA labels for accessibility
8. ✅ Improve error messages (user-friendly)

### **Phase 3 (Medium):**
9. ✅ Refactor into modular structure (separate CSS/JS)
10. ✅ Add colorblind-safe palettes
11. ✅ Consistent timeout configuration
12. ✅ Better responsive design (more breakpoints)

### **Phase 4 (Nice-to-have):**
13. ✅ Service Worker for offline capability
14. ✅ Advanced loading states/skeleton screens
15. ✅ Error logging/monitoring
16. ✅ Performance monitoring (Core Web Vitals)

---

## 📚 CODING STANDARDS VIOLATIONS

| Category | Issue | Example |
|----------|-------|---------|
| Naming | Unclear variable names | `const r = pcData.result;` → use descriptive names |
| Comments | Missing JSDoc | Functions lack documentation |
| Consistency | Mixed arrow/regular functions | Use arrow functions consistently |
| DRY | Repeated error handling | Consolidate into utility function |
| Constants | Magic numbers | Use named constants for API URLs |

---

## ✨ RECOMMENDATIONS SUMMARY

**Strengths:**
- Clean UI/UX design
- Good use of free public APIs
- Responsive layout basics
- Error handling present

**Weaknesses:**
- Input validation missing
- Race conditions possible
- Memory/performance issues
- Poor accessibility
- Monolithic structure
- Unclear error messages

**Estimated Effort to Fix:**
- Critical issues: 4-6 hours
- Major issues: 8-12 hours
- Minor + refactoring: 16-20 hours
- **Total: ~2-3 days for production-ready code**

---

*End of Review*
