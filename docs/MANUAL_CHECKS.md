# Manual checks

Values the pipeline cannot verify by itself. Work through these after the first run and after each September (new catchments) and March (offer day). Re-run `python -m pipeline.derive && python -m pipeline.export` after changing any seed file.

## 1. School gate coordinates (`data/seed/school_gates.csv`)

All three rows are seeded from the council's own 'Nearest Secondary Schools and Sixth Form Colleges' / 'Nearest Primary and Junior Schools' map layers and marked `verified=0`. Those points may be building centres rather than the main pedestrian gate the council measures to.

For each school, open [solihull.gov.uk/onlinemaps](https://www.solihull.gov.uk/onlinemaps), find the main pedestrian gate, right-click (or use the map's coordinate tool) to read its latitude and longitude, update `lat`/`lng`, and set `verified` to `1`.

| URN | School | Seed point |
|---|---|---|
| 136310 | Tudor Grange Academy Solihull (Dingle Lane) | 52.404559, -1.793016 |
| 136994 | Alderbrook School (Blossomfield Road) | 52.406194, -1.797301 |
| 139007 | Tudor Grange Primary Academy St James | 52.408030, -1.827502 |

A check: for your own address, the council's 'Nearest Secondary Schools' tool shows the official distance. The pack's figure (postcode centroid to gate) should be within about 0.1 mile of it.

## 2. Admissions history conflicts

Parsed automatically and flagged on every run (`source_runs` note for `admissions`):

| School | Year | Offer-day table (used for indicators) | Catchment map panel |
|---|---|---|---|
| Tudor Grange Academy Solihull | 2025 | Distance 0.14 mi | Priority 7 Distance 0.315 mi |
| Alderbrook School | 2025 | Sibling (Out of Catchment) 3.75 mi | Priority 6 Distance 0.405 mi |

Both agree for 2024 (TGA catchment 2.42 mi; Alderbrook distance 0.54 / 0.546 mi). The map panels may show the position after waiting-list movement, but neither document says so. Ask Solihull admissions (or check the admissions booklet) which point in the cycle each figure refers to. Source documents:

* How secondary places were offered 2024, 2025 and 2026 (linked from solihull.gov.uk 'Starting primary or secondary school')
* Alderbrook-School-Catchment-Map.pdf and TGAS-Catchment-Map.pdf (linked from the council's secondary schools page)

Your brief's Alderbrook seed values (2025 Priority 6 0.405 mi, 2024 Priority 5 0.546 mi, 2023 Sibling 1.745 mi) match the catchment map PDF exactly. The 2023 row is printed as 'Criteria 3 Sibling' on the map.

TGA last-offer data was found (no manual entry needed): offer day 2026 Distance 0.8 mi, 2025 Distance 0.14 mi, 2024 Catchment (without sibling) 2.42 mi; map panel 2023 Catchment Area 2.278 mi.

Not published in any document found: applications and first preferences per school. Add them to `data/seed/admissions_history.csv` if you obtain them (rows with the same urn, year, entry_point and source_url as a parsed row are merged).

## 3. Catchment flags for five test postcodes

Check each on [solihull.gov.uk/onlinemaps](https://www.solihull.gov.uk/onlinemaps) ('Secondary School Catchment Areas'). Pack values on 3 Oct 2026. These five, plus five others, were tested against the council's own server-side ArcGIS query and all matched.

| Postcode | Pack says (secondary catchments) | Why it is a useful test |
|---|---|---|
| B90 3DF | Alderbrook only | Your reference postcode |
| B91 3PD | Tudor Grange Academy Solihull only | TGA's own postcode |
| B91 1UA | Alderbrook only | Near the TGA/Alderbrook boundary (0.79 mi to TGA gate) |
| B90 1GS | Tudor Grange Academy Solihull and Light Hall | Overlapping (shared) zone |
| B90 1FQ | Alderbrook and Light Hall | Overlapping (shared) zone |

Postcodes are tested at their centroid. If your address is near a boundary, check the address itself.

## 4. Data that needs your input

| Item | Why | What to do |
|---|---|---|
| KS2/KS4 performance tables | compare-school-performance.service.gov.uk blocks automated clients (HTTP 403). The pipeline does not impersonate a browser. | In a browser, open https://www.compare-school-performance.service.gov.uk/download-data. For each of the latest 3 years choose 'Local authority' for each of Solihull, Birmingham, Warwickshire and Worcestershire, tick 'Key stage 2 results (final)' and 'Key stage 4 results (final)', then 'Data in CSV format'. Save the ZIPs unchanged into `data/manual/performance/` and run `python -m pipeline.run --sources performance`. |
| EPC certificates | The EPC API needs a personal bearer token. | Sign in at https://get-energy-performance-data.communities.gov.uk/ with GOV.UK One Login, copy the token from 'My account' into `.env` as `EPC_API_TOKEN=...`, then `python -m pipeline.run --sources epc`. Alternatively download the domestic bulk CSV for Solihull, Bromsgrove, Stratford-on-Avon and Warwick into `data/manual/epc/`. Until then the price score uses the house-price proxy and GBP per square metre is unavailable. |

## 5. Spot checks against official sites

`python -m pipeline.validate` prints five random postcodes with all metrics and the official page to compare each against (Land Registry, police.uk, IMD by postcode, Nomis). Checks already done during the build:

* PPD transaction for 37 Bronte Farm Road, B90 3DE (GBP 385,000, 23 Jul 2026) matches HM Land Registry linked data.
* LSOA E01010203 crimes for Aug 2026: 61 in the pack, 61 from the police API using the LSOA polygon as the search area.
* IMD deciles for E01010203 match the IoD2025 File 7 row; ONSPD's IMD rank (24120) matches too.
* Census OA E00051573 (TS021/TS030) values match the Nomis API.
