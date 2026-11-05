-- The public Streamlit app holds the weakest credentials: if they leak,
-- nobody can change anything with them.
GRANT USAGE ON SCHEMA public TO pipeline, app;
GRANT SELECT, INSERT, UPDATE, DELETE ON raw_ads, raw_deals, raw_fx, clean_ads, clean_deals TO pipeline;
GRANT SELECT ON raw_ads, raw_deals, raw_fx, clean_ads, clean_deals TO app;
