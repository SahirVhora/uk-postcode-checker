# UK Postcode Checker

**Quick demographic lookup for UK postcodes - crime charts, census breakdowns, schools, planning extensions, and transport. Fast and simple.**

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
| 🏗️ **Planning Extensions** | Searchable five-year extension applications within 1 km via PlanIt |
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
| [PlanIt](https://www.planit.org.uk/api/) | Nearby planning extension applications | No key; rate limited |
| [Environment Agency](https://environment.data.gov.uk/flood-monitoring/doc/reference) | Flood risk areas | Open Government Licence |
| [Chart.js](https://cdnjs.cloudflare.com) | Canvas charts | MIT |

## Area Pack (Shirley / Solihull)

A permanent local area-intelligence database built only from official open data, so a house search needs no paid service. It covers every live postcode in B90, B91 and B94 (configurable in `config/area.yaml`) and adds:

* **Three extra cards** in `index.html` for postcodes in the pack: secondary admissions (Tudor Grange Academy Solihull and Alderbrook catchments, gate distances, likely admission category, offer history), sold prices (Land Registry, plus EPC floor areas when loaded), and an area score with breakdown bars, weight sliders and a budget box. Any other postcode behaves exactly as before.
* **[shortlist.html](shortlist.html)**: every postcode ranked by score, with filters (catchment, budget, minimum score, outcode), a Leaflet map of postcode centres coloured by score, and CSV export.
* **A text report**: `python -m pipeline.report "B90 3DF"`.

Only derived per-postcode values are published in `data/area-pack/`. Catchment polygons, LSOA boundaries, the master database and raw downloads stay on your machine (`data/local/`, `pipeline/cache/`, both gitignored), and house numbers are never published.

### Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env        # optional: add EPC_API_TOKEN (see docs/MANUAL_CHECKS.md)
```

### Commands

| Command | What it does |
|---|---|
| `python -m pipeline.run --sources all` | Fetch every source (using the cache where present), load `data/local/area.db`, compute distances, metrics and scores |
| `python -m pipeline.run --sources ppd,police --refresh` | Re-download the named sources, ignoring the cache |
| `python -m pipeline.run --offline` | Rebuild the database from `pipeline/cache/` only, no network |
| `python -m pipeline.derive` | Recompute distances, metrics and scores after editing `config/scoring.yaml` |
| `python -m pipeline.export` | Write the public pack to `data/area-pack/` (refuses to write polygons) |
| `python -m pipeline.report "B90 3DF"` | One-page text profile |
| `python -m pipeline.validate` | Row counts, null rates, PPD to EPC match rate, five spot-check postcodes |

Sources: `onspd, catchments, gias, ofsted, performance, gates, admissions, ppd, epc, census, imd, lsoa_boundaries, police, osm`. A source that cannot run without your input (KS2/KS4 downloads, EPC token) is reported as `skipped_manual_input_needed` with instructions; everything else still builds.

To view the pages locally, serve the folder (browsers block `fetch` from `file://`):

```bash
python -m http.server 8000   # then open http://localhost:8000/ and /shortlist.html
```

### Monthly refresh

```bash
python -m pipeline.run --sources all --refresh
python -m pipeline.validate
python -m pipeline.export
git add data/area-pack && git commit -m "data: refresh area pack"
```

### Documentation

* [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md): every source, how it is discovered, licence, refresh cadence, caveats
* [docs/SCORING.md](docs/SCORING.md): the scoring formula and defaults
* [docs/MANUAL_CHECKS.md](docs/MANUAL_CHECKS.md): values to verify by hand (gate points, admissions conflicts, test postcodes) and data that needs your input

### Licences and attribution

Area Pack data: Contains HM Land Registry data (c) Crown copyright and database right, licensed under the Open Government Licence v3.0. Contains public sector information licensed under the Open Government Licence v3.0 (ONS, DfE, Ofsted, MHCLG, data.police.uk). Contains OS data (c) Crown copyright and database right, and Royal Mail data (c) Royal Mail copyright and database right. Map data (c) OpenStreetMap contributors, Open Database Licence. Catchment flags are derived from Solihull Council online maps; boundaries are not republished.

## 🔗 Also in the UK Property Toolkit

- **[UK-HomeFinder](https://github.com/SahirVhora/UK-HomeFinder)** - Property comparison tracker, SDLT calculator, readiness checklist, Rightmove/Zoopla URL parser

## Notes

- Crime data fetched for the latest reliable month in the Police API
- Census data from 2021 via LSOA geography codes
- School catchment boundaries are indicative - confirm with local council
- Planning matches are identified from application descriptions and may be incomplete - confirm with the local planning authority
- Privacy-first: no user data stored or transmitted

## License

MIT - see [LICENSE](LICENSE)
