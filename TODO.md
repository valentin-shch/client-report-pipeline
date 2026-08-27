# TODO

Things worth reconsidering later. Not blocking, just flagged.

- Generator reads the real system clock (`pd.Timestamp.today()`), so re-running
  it shifts every date even with the same seed. Good for keeping the demo fresh,
  but raw output isn't byte-reproducible run to run. `reports.run --anchor` pins
  a report's period, not the underlying data — an env var to freeze the end date
  for tests would.

- CRM `deal_value` is sampled uniform per client (inline TODO in
  `data/generate.py`). A real CRM's deal sizes are long-tailed, not flat.

- Missing `conversion_value` is imputed with a mean revenue-per-conversion by
  client+channel (`pipeline/clean.py`). Coarse — a per-campaign or per-month
  rate would be more accurate if it turns out to skew the channel comparisons.

- `pipeline/clean.py` treats LinkedIn spend as USD and converts it to EUR. That's
  a stated assumption about the account, not something in the raw file. If the
  generator ever grows a real currency column, key off that instead.

- `rolling_anomaly_score` is an O(n·window) Python loop (inline TODO in
  `pipeline/metrics.py`). Fine for 18 months of weekly points; revisit if it
  ever runs on daily data for every client at once.

- The "campaign stopped delivering" alert can't tell a planned seasonal end (a
  Black Friday campaign finishing on schedule) from an unplanned stop — there's
  no campaign calendar to check against (inline TODO in `reports/anomalies.py`).
  It flags both and asks the reader to confirm.

- The "spend up, no conversion lift" detector never fires on the current data:
  the generator ties conversions to spend and simulates no tracking breaks, so
  nothing triggers it. It's unit-tested but never exercised end to end — it's
  there for a real tracking break, which the synthetic data doesn't produce.

- `campaign_theme` is title-cased in `pipeline/clean.py`, so "BlackFriday" comes
  out as "Blackfriday" in report and alert text. Cosmetic; a small mapping would
  fix the known ones.

- The preview app embeds the report in an iframe with an estimated height
  (`app/lib.py`) — `st.components.html` can't self-size. There's a little slack
  at the bottom and `scrolling=True` as a backstop. A real custom component
  could measure the content and post its height back.

- Report chart polish: on a heavy week the "Spend and revenue by day" legend can
  sit over the bars. Move it above the plot area.
