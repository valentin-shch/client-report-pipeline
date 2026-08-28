# TODO

Things worth reconsidering later. Not blocking, just flagged.

- Generator dates still drift run to run. `CRP_DATA_END` pins the end of the
  window (see `.env.example`), which makes a run reproducible, but the committed
  `data/` and `samples/` are only stable if everyone regenerates with the same
  value set. Worth wiring `CRP_DATA_END` into CI so the checked-in artefacts stop
  moving.

- CRM `deal_value` is sampled uniform per client (inline TODO in
  `data/generate.py`). A real CRM's deal sizes are long-tailed, not flat.

- `pipeline/clean.py` treats LinkedIn spend as USD and converts it to EUR. That's
  a stated assumption about the account, not something in the raw file. If the
  generator ever grows a real currency column, key off that instead.

- The "campaign stopped delivering" alert can't tell a planned seasonal end (a
  Black Friday campaign finishing on schedule) from an unplanned stop — there's
  no campaign calendar to check against (inline TODO in `reports/anomalies.py`).
  It flags both and asks the reader to confirm.

- The "spend up, no conversion lift" detector never fires on the current data:
  the generator ties conversions to spend and simulates no tracking breaks, so
  nothing triggers it. It's unit-tested but never exercised end to end — it's
  there for a real tracking break, which the synthetic data doesn't produce.

- `app/components/report_frame` talks the Streamlit component postMessage
  protocol directly rather than pulling in `streamlit-component-lib`. Small and
  stable, but if a future Streamlit changes that protocol the embed height
  breaks silently — worth a glance on each Streamlit bump.
