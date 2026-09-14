# Rent Prediction + Dual-Scenario Cash Flow Engine

**Goal:** Given an address (or a set of property characteristics), predict (a) monthly long-term rent, (b) nightly short-term rate and expected occupancy, then compare both income paths on cash flow and report the break-even occupancy that makes STR beat LTR.

**Scope for v1:** One metro. Pick one where Inside Airbnb has good coverage *and* the county assessor publishes bulk data. Austin, Nashville, Denver, and Portland are all reasonable. Do not start multi-city.

---

## 1. Data sources

| Source | What you get | Cost | Notes |
|---|---|---|---|
| **RentCast API** | Active rental listings, rent estimates, property records | Free tier (~50 calls/mo), cheap paid tiers | Your LTR ground truth. Pull listings, not their estimates — you're building your own estimator. |
| **Inside Airbnb** | Listing snapshots per city: nightly price, min nights, reviews, availability calendar, lat/lon, bedrooms | Free, CSV downloads | Your STR ground truth. Grab several snapshot dates for the same city — that's how you get seasonality. |
| **County assessor / recorder bulk files** | Square footage, year built, lot size, beds/baths, last sale price and date | Free | The backbone of property characteristics. Format is ugly and county-specific; budget real time here. |
| **Census ACS API** | Tract-level median income, owner/renter split, household size, commute times | Free, needs API key | Join on census tract via lat/lon. |
| **FRED** | 30-yr mortgage rate series | Free | Only needed for the cash flow layer, not the models. |
| **OpenStreetMap / Overpass** | Distance to downtown, transit stops, parks, restaurants | Free | Optional for v1, high payoff for v2. Good "impressive" feature. |

**Occupancy is the hard part.** Inside Airbnb gives you a calendar, but blocked ≠ booked. The standard workaround is the *review-rate proxy*: estimate bookings from review counts, assume a review rate (~50%) and average stay length, cap at max nights. It's imperfect — say so explicitly in your README. Being upfront about a known-weak proxy reads as competence, not weakness.

---

## 2. Schema

Keep raw and modeling layers separate. Raw tables are append-only dumps; feature tables are rebuilt.

```
properties
  property_id PK, address, lat, lon, census_tract,
  beds, baths, sqft, lot_sqft, year_built, property_type,
  last_sale_price, last_sale_date, source, ingested_at

ltr_listings
  listing_id PK, property_id FK (nullable — fuzzy match),
  lat, lon, beds, baths, sqft, monthly_rent,
  listed_date, observed_date, source

str_listings
  str_id PK, snapshot_date, lat, lon, beds, baths, accommodates,
  nightly_price, cleaning_fee, min_nights,
  review_count, reviews_per_month, first_review, last_review,
  room_type, license_status

str_calendar
  str_id FK, date, available BOOL, price
  -- large table; partition by month

tract_features
  census_tract PK, year, median_income, pct_renter,
  median_household_size, median_commute_min, population

model_runs
  run_id PK, model_type, trained_at, train_cutoff_date,
  metrics_json, artifact_path
```

`model_runs` matters more than it looks. It's what separates a notebook from a project — you can answer "which model made this prediction and how good was it?"

---

## 3. Features

**Property (both models)**
- beds, baths, sqft, lot_sqft, year_built, property_type
- beds × baths interaction, sqft per bed
- age = current_year − year_built

**Location (both models)**
- tract median income, pct_renter, median household size
- distance to city center (haversine)
- distance to nearest transit stop, park (if you add OSM)
- neighborhood label — use the Inside Airbnb `neighbourhood` field as a categorical, target-encode it

**Market / time**
- month (cyclical: sin/cos encoding, not raw integer)
- local active listing count within 1km at observation date
- rolling median rent of comparable units in tract, trailing 90 days

**STR-only**
- accommodates, room_type (entire home vs private room — huge effect)
- min_nights
- review_count, reviews_per_month, days since first review (listing maturity)
- license_status if the city publishes it — regulation is a massive price driver

**Leakage traps to avoid**
- Never use `last_review` date or review counts *from after* your prediction date.
- Never use the property's own current listing price as a feature for itself.
- Don't include `price` in `str_calendar` as a feature for predicting nightly price.

---

## 4. Models

Train three separate models. Don't try to make one model do everything.

**Model A — long-term monthly rent.** Target: `monthly_rent`. Regression.

**Model B — STR nightly rate.** Target: `nightly_price`. Regression.

**Model C — STR occupancy.** Target: estimated occupancy rate (0–1) from the review proxy. Regression, clipped to [0,1].

**Progression for each** — this is the learning part, so actually do all three steps and record the numbers:

1. **Single decision tree**, depth capped at 4–5. Plot it. Look at the splits. You'll see sqft and beds dominate, and the tree structure will tell you something real about the market. This is the step people skip and it's the one that builds intuition.
2. **Random forest.** Your honest baseline. Note how much the variance drops vs. the single tree. Pull `feature_importances_`, then also do permutation importance — they disagree, and understanding *why* is worth an hour.
3. **Gradient boosting** (LightGBM or XGBoost). This will win. Tune `learning_rate`, `num_leaves`/`max_depth`, `min_child_samples` — not much else matters at first.

**Prediction intervals.** Point estimates are useless to an investor deciding on a purchase. Two easy options: LightGBM with `objective='quantile'` trained at alpha 0.1 / 0.5 / 0.9, or a random forest where you keep per-tree predictions and take percentiles. The quantile approach is cleaner. Ship intervals, not points.

**Validation — this is the thing that will actually impress a reviewer.** Do *not* use `train_test_split` with shuffling. Real estate has strong temporal drift and near-duplicate listings, so random splits leak and give you a fake-good R². Instead:

- Split by date: train on everything before cutoff T, test on after.
- Do this at several cutoffs (rolling-origin / expanding window) and report mean ± std.
- Additionally hold out a *geographic* slice — train on some tracts, test on unseen ones — to see whether you've memorized neighborhoods.

Report MAE in dollars, not just R². "Median absolute error of $147/month" is a sentence a human understands.

---

## 5. The cash flow layer

This is pure arithmetic, no ML, and it's what turns a model into a product.

```
LTR annual net = (monthly_rent × 12)
                 − vacancy (× ~8%)
                 − management (× ~8%)
                 − maintenance, taxes, insurance, HOA

STR annual net = (nightly_rate × 365 × occupancy)
                 + cleaning fee revenue
                 − cleaning cost per turnover
                 − STR management (× ~20%)
                 − supplies, utilities, platform fees (~3%)
                 − maintenance, taxes, insurance, HOA
```

Then: **break-even occupancy** = the occupancy rate at which STR net equals LTR net. Solve it directly — it's one line of algebra. Output it alongside your *predicted* occupancy, so the user sees "you need 58% to beat renting, and the model predicts 64% ± 9%."

Layer purchase price and a FRED mortgage rate on top and you get cap rate, cash-on-cash, and DSCR. Make every assumption (management %, vacancy %, maintenance) a user-adjustable input with a sane default. Investors will not trust hardcoded numbers.

---

## 6. Stack and build order

**Stack**
- pandas, scikit-learn, LightGBM — modeling
- Postgres (+ PostGIS once you're doing distance queries) — storage
- FastAPI — one `/predict` endpoint taking property characteristics, returning both scenarios with intervals
- Streamlit — v1 UI. Form on the left, results on the right. Swap to React later if you want the front-end credential.
- joblib for model artifacts, a plain `Makefile` or `justfile` for ingest/train/serve commands

**Build order — get each step working before the next**

1. Download one Inside Airbnb city snapshot. Load to Postgres. That's it.
2. Notebook: EDA on nightly price. Single tree → RF → LightGBM for Model B. Temporal split from day one.
3. Add assessor bulk file + RentCast pulls. Build Model A the same way.
4. Build the occupancy proxy and Model C.
5. Write the cash flow functions as a pure Python module with unit tests. Easy to test, and tests in the repo look good.
6. Wrap in FastAPI. One endpoint. Pydantic models for request/response.
7. Streamlit front end hitting the API.
8. Deploy — Railway or Fly.io, cheap and painless. **A deployed mediocre model beats a brilliant notebook.**
9. README with: the problem, your validation approach, the occupancy proxy caveat, and a screenshot.

**Rough effort:** steps 1–4 are the bulk of the learning and probably 60% of total time. Steps 6–8 are a weekend. Step 5 is an evening. Don't let the infrastructure eat the modeling time — that's the classic failure mode on portfolio projects.

---

## 7. What makes this stand out

Most portfolio regression projects are "I predicted house prices on the Kaggle Ames dataset with R² 0.91." Yours differs on four axes, and you should say so explicitly in the README:

1. You assembled the dataset yourself from four messy public sources.
2. You used temporal and geographic validation instead of random splits, and you can explain why.
3. You ship prediction intervals, not point estimates.
4. The output is a decision (STR vs LTR, with a break-even number), not a number.

Only the fourth one is about real estate. The other three are things a hiring manager reads as "this person has actually thought about deployment."
