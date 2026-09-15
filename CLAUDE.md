# CLAUDE.md

Rent prediction + dual-scenario (long-term vs short-term rental) cash flow engine.
Predicts monthly rent, STR nightly rate, and occupancy, then compares both income
paths and reports break-even occupancy.

Full architecture, data schema, feature list, and build order: @docs/spec.md

## Stack

- Python 3.11, pandas, scikit-learn, LightGBM
- Postgres (PostGIS once distance features land)
- FastAPI for the prediction endpoint
- Streamlit for the v1 UI
- joblib for model artifacts

## Layout

```
data/          raw downloads — gitignored, never commit
notebooks/     exploration and model development
src/
  ingest/      one module per data source
  features/    feature engineering, shared by all models
  models/      training scripts, one per target
  cashflow/    pure-Python LTR/STR math, unit tested
  api/         FastAPI app
docs/          spec and notes
tests/
```

## Conventions

- Validation is **always temporal**. Never use `train_test_split` with shuffling —
  real estate has strong time drift and random splits leak. Split by date, and
  report rolling-origin results across several cutoffs.
- Report MAE in dollars alongside R². Dollar error is the number that matters.
- Models output prediction intervals (LightGBM quantile objective), not point
  estimates.
- Cash flow assumptions (vacancy %, management %, maintenance) are always
  parameters with defaults, never hardcoded constants.
- Secrets go in `.env`, loaded via `python-dotenv`. Never inline an API key.
- The `cashflow/` module stays pure — no I/O, no database calls. It should be
  testable with plain function calls.

## Known caveats

- STR occupancy is estimated from a review-rate proxy, not real booking data.
  It is a documented approximation. Don't present it as ground truth in output
  or in the README.

## Working with me on this

I'm learning as I build. When you write something non-obvious — a pandas idiom,
a modeling choice, a git operation — explain briefly why, not just what.
Prefer clear code over clever code.
