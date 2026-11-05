-- Rows as the API returned them. `date` is parsed for filtering and the key;
-- `date_raw` keeps the platform's own format.
CREATE TABLE IF NOT EXISTS raw_ads (
    source           text NOT NULL,
    client           text NOT NULL,
    date             date NOT NULL,
    date_raw         text NOT NULL,
    channel          text NOT NULL,
    campaign_name    text NOT NULL,
    spend            double precision NOT NULL,
    impressions      integer NOT NULL,
    clicks           integer NOT NULL,
    conversions      integer NOT NULL,
    conversion_value double precision,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, client, date, campaign_name)
);

CREATE TABLE IF NOT EXISTS raw_deals (
    deal_id         text PRIMARY KEY,
    client          text NOT NULL,
    created_date    date NOT NULL,
    closed_date     date,
    stage           text NOT NULL,
    deal_value      double precision NOT NULL,
    source_campaign text,
    updated_at      date NOT NULL,
    ingested_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw_fx (
    date        date PRIMARY KEY,
    usd_eur     double precision NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clean_ads (
    date                     date NOT NULL,
    client                   text NOT NULL,
    channel                  text NOT NULL,
    campaign_name            text NOT NULL,
    spend                    double precision NOT NULL,
    impressions              integer NOT NULL,
    clicks                   integer NOT NULL,
    conversions              integer NOT NULL,
    conversion_value         double precision,
    conversion_value_imputed boolean NOT NULL,
    campaign_convention      text,
    campaign_country         text,
    campaign_type            text,
    campaign_theme           text,
    campaign_period          text,
    UNIQUE (client, date, channel, campaign_name)
);

CREATE TABLE IF NOT EXISTS clean_deals (
    deal_id            text PRIMARY KEY,
    client             text NOT NULL,
    created_date       date NOT NULL,
    closed_date        date,
    stage              text NOT NULL,
    deal_value         double precision NOT NULL,
    source_campaign    text,
    attribution_status text NOT NULL,
    attributed_channel text
);
