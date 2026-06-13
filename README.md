# UK Postcode Checker

**Quick demographic lookup for UK postcodes - crime charts, census breakdowns, schools, and transport. Fast and simple.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Toolkit](https://img.shields.io/badge/part%20of-UK%20Property%20Toolkit-blue)](https://github.com/SahirVhora?tab=repositories&q=uk-property+OR+HomeFinder+OR+postcode-checker)

Part of the **[UK Property Toolkit](https://github.com/SahirVhora?tab=repositories&q=uk-property+OR+HomeFinder+OR+postcode-checker)** - focused free tools for UK home buyers.

| Tool | Purpose | Best For |
|---|---|---|
| [UK-HomeFinder](https://github.com/SahirVhora/UK-HomeFinder) | Property tracking + SDLT + checklist | Active buyers comparing properties |
| **uk-postcode-checker** ← you are here | Quick demographic lookup | Fast postcode overview |

👉 **[Launch UK Postcode Checker](https://sahirvhora.github.io/uk-postcode-checker)**

---

## Features

Enter any UK postcode and instantly see:

| Card | Data Source |
|---|---|
| 📍 **Location** | Ward, district, LSOA codes via postcodes.io |
| 🚔 **Crime** | Street-level stats with Chart.js canvas (Police Data API) |
| 👥 **Ethnicity** | Census 2021 breakdown with pie chart (ONS Beta API) |
| 🏠 **Housing Tenure** | Owned vs rented vs social with chart (ONS Beta API) |
| 🏫 **Schools Nearby** | 2-mile radius with Google Places ratings (optional) |
| ✝ **Religion** | Census 2021 distribution with chart (ONS Beta API) |
| 🚌 **Transport** | Train stations and bus stops near postcode |

## Quick Start

```bash
git clone https://github.com/SahirVhora/uk-postcode-checker.git
cd uk-postcode-checker
open index.html
```

No server, no install, no build step. Single HTML file - just open it.

## Google Places API (Optional)

To enable school star ratings:
1. Get a key from [Google Cloud Console](https://console.cloud.google.com) - enable **Places API**
2. Open `index.html` and set `const GOOGLE_PLACES_KEY = "YOUR_KEY"`
3. Without a key, the column shows a muted note and everything else still works

## APIs Used

| API | Purpose | Auth |
|---|---|---|
| [Postcodes.io](https://postcodes.io) | Lat/lng, ward, district, LSOA | None |
| [Police Data API](https://data.police.uk/docs/) | Street-level crime | Open Government Licence |
| [ONS Beta API](https://api.beta.ons.gov.uk) | Census 2021 ethnicity & tenure | Open Government Licence |
| [OpenStreetMap Overpass](https://overpass-api.de) | Schools near postcode | Open (ODbL) |
| [Environment Agency](https://environment.data.gov.uk/flood-monitoring/doc/reference) | Flood risk areas | Open Government Licence |
| [Chart.js](https://cdnjs.cloudflare.com) | Canvas charts | MIT |

## 🔗 Also in the UK Property Toolkit

- **[UK-HomeFinder](https://github.com/SahirVhora/UK-HomeFinder)** - Property comparison tracker, SDLT calculator, readiness checklist, Rightmove/Zoopla URL parser

## Notes

- Crime data fetched for the latest reliable month in the Police API
- Census data from 2021 via LSOA geography codes
- School catchment boundaries are indicative - confirm with local council
- Privacy-first: no user data stored or transmitted

## License

MIT - see [LICENSE](LICENSE)
