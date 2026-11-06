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

- LinkedIn's labels run a day behind, so after the cleaning fix its newest row
  is dated today, a day that isn't over. Reports only cover finished weeks, so
  it never reaches one, but a daily view would need to drop it.

- A job killed mid-batch leaves no row for the clients it hadn't reached, so
  `--retry-failed` can't see them. A plain re-run covers them. Queued rows
  written up front would fix it properly.

- A report stuck on `sending` means a process died mid-send and nobody knows if
  the email went. On purpose it's never re-sent by itself; check the inbox, then
  set the status by hand. A late email beats a duplicate one.

- `--force` wipes a report's send history, so a forced resend doesn't count
  towards that day's cap. A separate send log would fix both.

- `DEMO_RECIPIENT` can appear in `reports.error` if the mail server refuses it,
  and the app role can read that. Don't show raw errors on a public page.

## Won't fix

- `clean.py` converts LinkedIn spend USD -> EUR. The raw file doesn't say it's
  USD; it's an assumption about the account, and it's in the data-quality
  summary. Fine unless the generator ever gets a real currency column.

- "Campaign stopped delivering" can't tell a planned seasonal end from a real
  one. It just asks you to check. A campaign calendar would fix it properly.
