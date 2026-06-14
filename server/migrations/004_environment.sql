-- Tag each session with where the server ran: 'local' (dev) or 'online'
-- (deployed). Derived from the DEPLOY_ENV env var in recorder.py; existing
-- rows backfill to 'local' via the column default.

ALTER TABLE public.sessions
    ADD COLUMN IF NOT EXISTS environment text NOT NULL DEFAULT 'local';
