# UK Postcode Checker

A self-contained property research dashboard for UK postcodes. Enter any UK postcode and
instantly see location details, crime stats, census demographics, nearby schools, and
flood risk — all from free public APIs, no backend required.

---

## How to run

Just open the file in a browser:

```
open ~/projects/claude-experiments/uk-postcode-checker/index.html
```

Or double-click `index.html` in your file manager. No server, no install, no build step needed.

---

## Google Places API key (optional)

The schools card has a column for Google star ratings. To enable it:

1. Go to https://console.cloud.google.com
2. Create a project → Enable **Places API**
3. Create an API key (restrict it to your domain for safety)
4. Open `index.html`, find this line near the top of the `<script>` block:

   ```js
   const GOOGLE_PLACES_KEY = "";
   ```

5. Paste your key between the quotes and save.

Without a key, the column shows a muted note and everything else still works.

---

## APIs used

| API | Used for | Terms |
|-----|----------|-------|
| [Postcodes.io](https://postcodes.io) | Lat/lng, ward, district, LSOA code | Open — no auth needed |
| [Police Data API](https://data.police.uk/docs/) | Street-level crime data | Open Government Licence |
| [ONS Beta API](https://api.beta.ons.gov.uk) | Census 2021 ethnicity & tenure data | Open Government Licence |
| [DfE Education Estates API](https://educationestatesapi.education.gov.uk) | Schools near postcode | Public — no auth needed |
| [Environment Agency Flood API](https://environment.data.gov.uk/flood-monitoring/doc/reference) | Flood risk areas | Open Government Licence |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | Embedded map tile | ODbL — attribution required |
| [Chart.js CDN](https://cdnjs.cloudflare.com) | Charts | MIT |

---

## Folder structure

```
uk-postcode-checker/
├── index.html    ← The entire app (single file, open in browser)
├── README.md     ← This file
└── assets/       ← Reserved for future icons/images
```

---

## Notes

- Crime data is fetched for September 2024 (latest reliable month in the Police API).
- ONS Census data is from the 2021 census and uses LSOA geography codes.
- If the ONS beta API has CORS issues, the ethnicity/tenure cards show a fallback link to nomisweb.co.uk.
- School catchment boundaries are indicative — always confirm with the local council.
