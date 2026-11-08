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

-- One row per client per run. A failed row with its error is the dead letter:
-- `python -m runner --retry-failed` picks those up.
CREATE TABLE IF NOT EXISTS runs (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client        text NOT NULL,
    period        text NOT NULL,
    anchor        date NOT NULL,
    period_start  date NOT NULL,
    period_end    date NOT NULL,
    trigger       text NOT NULL CHECK (trigger IN ('schedule', 'manual')),
    status        text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    step          text,
    retries       integer NOT NULL DEFAULT 0,
    error         text,
    rows_ingested integer,
    steps         jsonb NOT NULL DEFAULT '[]',
    dq_summary    jsonb,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    batch         text
);

-- For databases made before batches existed.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS batch text;

-- status: pending -> approved -> sending -> sent, or send_failed. Sending is
-- claimed with a single UPDATE so two clicks can never send two emails.
CREATE TABLE IF NOT EXISTS reports (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       bigint REFERENCES runs (id),
    client       text NOT NULL,
    period       text NOT NULL,
    period_start date NOT NULL,
    period_end   date NOT NULL,
    theme        text NOT NULL,
    subject      text NOT NULL,
    html         text NOT NULL,
    alerts       jsonb NOT NULL DEFAULT '[]',
    status       text NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'approved', 'sending', 'sent', 'send_failed')),
    error        text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    approved_at  timestamptz,
    claimed_at   timestamptz,
    sent_at      timestamptz,
    UNIQUE (client, period, period_start, theme)
);

-- Passcode tries on the Approvals page. Five wrong ones in an hour lock
-- approvals for everyone, so guessing is slow even across sessions.
CREATE TABLE IF NOT EXISTS approval_attempts (
    at timestamptz NOT NULL DEFAULT now(),
    ok boolean NOT NULL
);
