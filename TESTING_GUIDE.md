# TESTING GUIDE - UK Postcode Checker

## ✅ What Was Fixed

The following improvements have been applied to `index.html`:

### 1. **Postcode Validation** ✓
- Added `isValidPostcode()` function with UK postcode regex
- Input now validates before API calls
- Error message displayed inline for invalid input

### 2. **Race Condition Prevention** ✓
- Implemented `AbortController` to cancel previous requests when clicking search multiple times
- Button shows "aria-busy" state for accessibility

### 3. **ARIA Labels** ✓
- Added `aria-label` to search input and button
- Added `aria-describedby` linking to error hint text
- Added `aria-live="polite"` for dynamic error updates
- Added `aria-busy` attribute to button

### 4. **Constants & Configuration** ✓
- Created `SEARCH_RADIUS` object for all distance searches (schools, buses, trains)
- Created `API_TIMEOUTS` for each API with consistent values
- Created `ERROR_MESSAGES` object with user-friendly error text

### 5. **Error Handling** ✓
- All fetch calls now use `searchAbortController.signal`
- Added proper timeout configuration on all API calls
- Error messages now distinguish between different types (not found vs timeout vs network)
- Added `AbortError` checks to avoid showing errors for cancelled requests

### 6. **JSDoc Comments** ✓
- Added comprehensive JSDoc for all functions
- Clear parameter and return type documentation
- Inline comments for complex logic

---

## 🧪 HOW TO TEST

### **Test Environment Setup**

```bash
# Open the file in your browser
# Option 1: Double-click index.html in File Explorer
# Option 2: Use a local server (recommended)
python -m http.server 8000
# Then visit http://localhost:8000
```

---

### **Test Case 1: Valid Postcode Search**

**Steps:**
1. Enter a valid UK postcode (e.g., `B90 2DH`, `SW1A 1AA`, `M1 1AD`)
2. Click "Search" button
3. Verify all 7 cards load with data

**Expected Results:**
- ✓ Location card shows district, ward, constituency, region, LSOA
- ✓ Crime card loads with recent statistics
- ✓ Ethnicity card shows census data
- ✓ Housing card shows tenure breakdown
- ✓ Schools card shows nearby schools
- ✓ Religion card shows religious demographics
- ✓ Transport card shows bus routes and stations
- ✓ Footer displays with data sources

**Valid UK Postcode Examples:**
- `B90 2DH` (Birmingham)
- `SW1A 1AA` (Westminster)
- `M1 1AD` (Manchester)
- `EH8 8DX` (Edinburgh)
- `CF10 1NZ` (Cardiff)

---

### **Test Case 2: Invalid Postcode Validation**

**Steps:**
1. Enter invalid postcodes and test each:
   - `ABC` (too short)
   - `12345` (wrong format)
   - `   ` (empty)
   - `XYZ QWE` (invalid format)

2. Try clicking "Search"

**Expected Results:**
- ✓ Error message appears: `"Please enter a valid UK postcode (e.g., B90 2DH)"`
- ✓ Cards do NOT load
- ✓ No API calls are made
- ✓ Error text appears inline, not in card
- ✓ Error clears when user enters valid postcode

---

### **Test Case 3: Empty Input**

**Steps:**
1. Click "Search" button without entering anything

**Expected Results:**
- ✓ Validation error appears
- ✓ No API calls made
- ✓ Button remains active

---

### **Test Case 4: Race Condition Prevention**

**Steps:**
1. Enter a valid postcode (e.g., `B90 2DH`)
2. Click "Search" button
3. Immediately click "Search" again before data loads (within 2-3 seconds)
4. Repeat step 3 multiple times

**Expected Results:**
- ✓ First request is cancelled
- ✓ Only the latest search is processed
- ✓ No duplicate API calls in network tab
- ✓ Cards show correct data from final search only
- ✓ No errors appear (abort errors are silent)

**Browser DevTools Verification:**
1. Open DevTools: `F12`
2. Go to "Network" tab
3. Click Search multiple times rapidly
4. Verify only the last request completes; earlier ones show `cancelled`

---

### **Test Case 5: Network Error Handling**

**Steps:**
1. Turn off internet connection (or use DevTools throttling)
2. Enter a valid postcode
3. Click "Search"

**Expected Results:**
- ✓ Error message appears: `"Network error. Please check your connection and try again."`
- ✓ Cards show error message (not blank)
- ✓ No console errors logged
- ✓ User can retry by entering another postcode

**Turn off Internet Using DevTools:**
1. Open DevTools (`F12`)
2. Go to "Network" tab
3. Click the "No throttling" dropdown → select "Offline"
4. Search and verify error handling

---

### **Test Case 6: Timeout Handling (Slow Network)**

**Steps:**
1. Open DevTools (`F12`)
2. Go to "Network" tab
3. Set throttling to "Slow 3G"
4. Search for a postcode

**Expected Results:**
- ✓ Spinner shows for longer
- ✓ Eventually either data loads OR timeout error appears
- ✓ No network errors or crashes
- ✓ Button is responsive after request completes

**Set Slow Network in DevTools:**
1. Network tab
2. "No throttling" → "Slow 3G"

---

### **Test Case 7: ARIA Accessibility**

**Steps:**
1. Open DevTools (`F12`)
2. Go to "Elements" tab
3. Inspect the search input element
4. Verify ARIA attributes present

**Expected Results - In HTML Inspector:**
- ✓ Input has `aria-label="Enter a UK postcode"`
- ✓ Input has `aria-describedby="postcode-hint"`
- ✓ Button has `aria-label="Search for postcode information"`
- ✓ Button has `aria-busy="true"` (while searching) / `"false"` (idle)
- ✓ Error hint div has `aria-live="polite"`

**Test with Screen Reader (Windows Narrator):**
1. Press `Windows + Enter` to open Narrator
2. Press `Tab` to navigate to input
3. Verify Narrator reads: "Enter a UK postcode"
4. Press Tab again to button
5. Verify Narrator reads: "Search for postcode information"
6. Click search and verify busy state is announced

---

### **Test Case 8: Postcode with Spaces**

**Steps:**
1. Enter postcode with space: `B90 2DH` (includes space)
2. Enter same postcode without space: `B902DH`
3. Enter with extra spaces: `B9   0   2DH`
4. Verify all three work the same

**Expected Results:**
- ✓ All three variations load same data
- ✓ Normalisation function removes spaces correctly
- ✓ Uppercase conversion works
- ✓ No validation errors

---

### **Test Case 9: Postcode Case Insensitivity**

**Steps:**
1. Search uppercase: `B90 2DH`
2. Search lowercase: `b90 2dh`
3. Search mixed case: `B90 2Dh`

**Expected Results:**
- ✓ All three return identical results
- ✓ All are normalized to uppercase internally

---

### **Test Case 10: Keyboard Navigation**

**Steps:**
1. Click on postcode input
2. Type a postcode
3. Press `Enter` key (don't click button)
4. Verify search executes

**Expected Results:**
- ✓ Search triggers from `Enter` key
- ✓ Same results as clicking button
- ✓ `e.preventDefault()` stops double submission

---

### **Test Case 11: Button States**

**Steps:**
1. Enter postcode
2. Click "Search"
3. Immediately watch the button during loading

**Expected Results:**
- ✓ Button text changes to "Searching…"
- ✓ Button becomes disabled (greyed out)
- ✓ `aria-busy="true"` attribute set
- ✓ Button text returns to "Search" when done
- ✓ Button becomes enabled again
- ✓ `aria-busy="false"` attribute set

---

### **Test Case 12: Error Messages Are User-Friendly**

**Test with Invalid Postcode:**
1. Enter `ABC`
2. Check error message

**Test with API timeout:**
1. Set network to "Slow 3G" in DevTools
2. Search for postcode that takes > 30s

**Expected Results:**
- ✓ Error messages are plain English (not technical)
- ✓ Suggest corrective action (e.g., "Please check and try again")
- ✓ Don't show raw HTTP status codes to user
- ✓ Differentiate between types: validation, timeout, network, not found

**Example Error Messages:**
- Invalid: `"Please enter a valid UK postcode (e.g., B90 2DH)"`
- Not found: `"Postcode not found. Please check and try again."`
- Network: `"Network error. Please check your connection and try again."`
- Timeout: `"Request took too long. Please try again."`

---

### **Test Case 13: Responsive Design (Mobile)**

**Steps:**
1. Open DevTools (`F12`)
2. Click device toggle icon
3. Select "iPhone 12" or similar
4. Search for a postcode
5. Verify layout

**Expected Results:**
- ✓ Single column layout on mobile (2 columns on desktop)
- ✓ Charts are readable
- ✓ Tables scroll horizontally if needed
- ✓ Button and input stack properly
- ✓ Text size is readable (not too small)

---

### **Test Case 14: Console Check (No Errors)**

**Steps:**
1. Open DevTools (`F12`)
2. Go to "Console" tab
3. Search for multiple postcodes
4. Verify console is clean

**Expected Results:**
- ✓ No red error messages
- ✓ No `undefined` references
- ✓ No deprecated API warnings
- ✓ Only normal info/logs (if any)

---

### **Test Case 15: Data Source Attribution**

**Steps:**
1. Perform a search
2. Scroll to bottom
3. Check footer

**Expected Results:**
- ✓ Footer displays with data sources
- ✓ Links to APIs are present:
  - Postcodes.io
  - Police API
  - ONS / Nomis Census 2021
  - OpenStreetMap
  - Ofsted

---

## 📊 Test Results Template

Use this to document your test results:

```markdown
| Test Case | Status | Notes |
|-----------|--------|-------|
| Valid Postcode | ✓ PASS | All cards loaded correctly |
| Invalid Postcode | ✓ PASS | Error shown, no API calls |
| Race Condition | ✓ PASS | Only final request processed |
| Network Error | ✓ PASS | User-friendly error message |
| ARIA Labels | ✓ PASS | All required attributes present |
| Keyboard Nav | ✓ PASS | Enter key works |
| Button States | ✓ PASS | Loading state displays |
| Mobile Layout | ✓ PASS | Single column responsive |
| Console Clean | ✓ PASS | No errors or warnings |
| Error Messages | ✓ PASS | User-friendly and clear |
```

---

## 🐛 Debugging Tips

### If postcodes aren't validating:
```javascript
// Check what postcode regex accepts
console.log(POSTCODE_REGEX.test("B90 2DH")); // Should be true
```

### If API timeouts occur:
1. Check `API_TIMEOUTS` constants — may need to increase
2. Check browser Network tab for slow requests
3. Verify API endpoints are responding

### If ARIA labels not working:
1. Open DevTools → Elements tab
2. Inspect input element
3. Verify attributes are present in HTML

### If validation error doesn't display:
1. Check `aria-live="polite"` element exists
2. Verify `showPostcodeError()` and `clearPostcodeError()` functions are called
3. Check CSS `.error-msg` styling is correct

---

## ✨ Improvements Summary

**Before → After:**

| Issue | Before | After |
|-------|--------|-------|
| Input Validation | None | Full postcode format validation |
| Race Conditions | Possible | Prevented with AbortController |
| Accessibility | No ARIA labels | Full ARIA support |
| Error Messages | Generic | User-friendly, contextual |
| Configuration | Magic numbers | Named constants |
| Documentation | Missing | JSDoc comments |
| Timeout Handling | Basic | Consistent API timeouts |

---

## 🎯 Quick Test Checklist

- [ ] Valid postcode loads all data
- [ ] Invalid postcode shows error
- [ ] Race condition test (multiple clicks)
- [ ] Network error handling
- [ ] Keyboard Enter key works
- [ ] Button shows loading state
- [ ] Error messages are clear
- [ ] ARIA labels present (DevTools)
- [ ] No console errors
- [ ] Mobile layout responsive
- [ ] Footer with sources displays

---

**All tests should PASS before considering code production-ready.**
