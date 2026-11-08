-- The public Streamlit app holds the weakest credentials: if they leak,
-- nobody can change anything with them.
GRANT USAGE ON SCHEMA public TO pipeline, app;
GRANT SELECT, INSERT, UPDATE, DELETE ON raw_ads, raw_deals, raw_fx, clean_ads, clean_deals TO pipeline;
GRANT SELECT ON raw_ads, raw_deals, raw_fx, clean_ads, clean_deals TO app;
GRANT SELECT, INSERT, UPDATE ON runs TO pipeline;
GRANT USAGE ON SEQUENCE runs_id_seq TO pipeline;
GRANT SELECT ON runs TO app;
GRANT SELECT, INSERT, UPDATE ON reports TO pipeline;
GRANT USAGE ON SEQUENCE reports_id_seq TO pipeline;
-- The app moves a report through its statuses and nothing else: it can never
-- change what a report says.
GRANT SELECT ON reports TO app;
GRANT UPDATE (status, error, approved_at, claimed_at, sent_at) ON reports TO app;
GRANT SELECT, INSERT ON approval_attempts TO app;
