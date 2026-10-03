# Area score

Code: `pipeline/score.py`. Weights and parameters: `config/scoring.yaml`. The browser recomputes the total with the same formula (`areaTotalScore` in `index.html` and `shortlist.html`); `tests/fixtures/score_parity.json` is checked by both the Python and the Node tests so the two cannot drift.

## Total

Four sub-scores, each 0 to 100:

```
total = sum(w_k * s_k) / sum(w_k)    over sub-scores k that have a value
```

Default weights: school 40, price/value 25, neighbourhood/safety 20, community 15. A missing sub-score is dropped and the others re-weighted; it never counts as 0. Rounding is half up to 2 decimals in both Python and JavaScript. The breakdown is always shown, never only the total.

## How components become 0 to 100

* **Percentile rank within the pool** (all live postcodes in the configured outcodes). Ties share their average rank. `pct = average_rank / (n - 1) * 100`, inverted (`100 - pct`) where lower is better. Postcodes with no value are left out of the ranking.
* **Fixed scales** for facts that should not depend on the rest of the pool: yes/no = 100/0, IMD deciles `(decile - 1) / 9 * 100` (10 = least deprived = 100), Ofsted judgements, Attainment 8.

Within a sub-score, components are combined with the same weighted mean, re-weighting away any component with no data.

## School (default 40)

| Component | Weight | Scale |
|---|---|---|
| In TGA catchment | 20 | yes 100 / no 0 |
| In Alderbrook catchment | 15 | yes 100 / no 0 |
| Distance to TGA gate | 15 | percentile, nearer is better |
| Distance to Alderbrook gate | 10 | percentile, nearer is better |
| Distance to TGPA St James | 5 | percentile, nearer is better |
| Historic admission safety | 20 | best of the two schools: `100 * years offered / years shown` for an applicant with no sibling who is not a feeder pupil, from the last 3 offer-day results |
| Ofsted | 7.5 | catchment school(s), or the nearest target school if in neither. Legacy quality of education grade 1/2/3/4 = 100/66.7/33.3/0; otherwise ungraded outcome text (Outstanding 100, Good 66.7, Requires improvement 33.3, Inadequate 0). Report-card-only schools give no value (re-weighted), because report cards are never collapsed into one grade. |
| KS4 attainment | 7.5 | latest Attainment 8: `(A8 - 30) / 40 * 100`, clamped 0 to 100. Progress 8 is not used, so 'not published' cannot distort it. No value until KS4 files are imported. |

**Cap**: a postcode in neither target catchment cannot score above 40.

## Price / value (default 25)

Values come from the finest level with at least 3 recent sales: postcode, then sector (e.g. B90 3), then outcode. Category A sales, last 24 months.

* With EPC data: median GBP per square metre (weight 50) and median price of 4-bed-equivalent homes (5+ habitable rooms, weight 50), both percentile, lower is better.
* Without EPC data (current state until a token or bulk file is supplied): **proxy** = median house price (detached, semi and terraced together, flats excluded), percentile, lower is better. The proxy is labelled on every card.
* **Budget penalty** (hard): if the family-home price (4-bed-equivalent median, or the house proxy) is above the budget (default GBP 550,000), the price sub-score is multiplied by 0.25. The budget can be changed on both pages; the penalty is recomputed in the browser from `price_raw` and `budget_value`.

## Neighbourhood / safety (default 20)

| Component | Weight | Scale |
|---|---|---|
| Family-relevant crime rate (burglary, vehicle crime, violence and sexual offences, robbery per 1,000 residents a year, LSOA) | 50 | percentile, lower is better |
| IMD crime decile | 25 | fixed |
| IMD overall decile | 25 | fixed |

The all-crime rate and the Solihull borough medians are shown for context but not scored, because shoplifting in shopping areas dominates all-crime counts.

## Community (default 15)

| Component | Weight | Scale |
|---|---|---|
| Asian % (Census 2021, output area) | 30 | percentile, higher is better |
| Muslim % (output area) | 30 | percentile, higher is better |
| Distance to nearest mosque | 20 | percentile, nearer is better |
| Distance to nearest halal food | 20 | percentile, nearer is better |

## Changing the model

Edit `config/scoring.yaml` (weights, budget, component weights, cap, penalty), then recompute and re-export without touching the network:

```bash
python -m pipeline.derive
python -m pipeline.export
```
