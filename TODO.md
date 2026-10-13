# TODO

Stuff I know about. Not blocking.

- The generator uses today's date unless you set `CRP_DATA_END`. The committed
  `data/` and `samples/` were built with `CRP_DATA_END=2026-07-31`; use that to
  reproduce them. CI runs unpinned on purpose so its reports stay fresh.

- CRM `deal_value` is a lognormal. Shape looks right; I never fitted it to
  anything real.

- The fake ad API's dataset ends 2028-12-31, so after that no new weeks
  appear. Moving `DATA_END` in `adsapi/data.py` is the whole fix.

- The API's rate limit keys on the caller's IP as forwarded by the proxy,
  which a caller could spoof. Fine for synthetic data behind a key.

## Won't fix

- `clean.py` converts LinkedIn spend USD -> EUR. The raw file doesn't say it's
  USD; it's an assumption about the account, and it's in the data-quality
  summary. Fine unless the generator ever gets a real currency column.

- "Campaign stopped delivering" can't tell a planned seasonal end from a real
  one. It just asks you to check. A campaign calendar would fix it properly.
