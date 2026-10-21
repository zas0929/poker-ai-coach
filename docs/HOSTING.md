# Hosting: Vercel + Render

This follows the existing Chess AI Coach setup: Next.js on Vercel, FastAPI on Render.
Create **separate Poker services**; do not overwrite Chess AI Coach or String Art Dnipro.

## Backend

Use `backend/` as the Docker build context, with `backend/Dockerfile`.
Render provides `PORT`; the image binds to that port. Health check: `/`.
Use exactly **one instance and one Uvicorn worker**: room state, turn timers and
WebSocket ownership are process-local. Horizontal scaling needs shared coordination first.

Set `POKER_ROOM_ORIGINS` to the exact HTTPS frontend origin, without a trailing slash.
The same list configures HTTP CORS and WebSocket Origin validation. Local defaults
remain `http://localhost:3000,http://127.0.0.1:3000`. Never use a wildcard.

### Durable storage on the free plan

Set the backend-only secret `POKER_DATABASE_URL` to a PostgreSQL connection URI.
For Supabase use the IPv4 **Session pooler** connection (port 5432), with the
project's database password percent-encoded in the URI. Alternatively omit the
password from the URI and set backend-only `PGPASSWORD` to its existing value;
libpq reads it directly, so special characters need no encoding. Never expose either value
through a `NEXT_PUBLIC_` variable or commit it. TLS is required by the driver;
prepared statements are disabled for pooler compatibility.

The backend creates its tables in the `poker_private` schema, revokes public
schema access and enables RLS on every table. It does not use Supabase's public
Data API or change the `public` schema. A dedicated database is preferred; sharing
an existing project requires its owner's approval and shares resource quotas.
Only run one backend instance against a given Poker schema.

On Render, missing `POKER_DATABASE_URL` prevents startup rather than silently
putting private records in ephemeral SQLite. Local development still uses SQLite
by default. SQLite with `POKER_DB_PATH` on a persistent disk is also supported
outside this free deployment.

Do not upload the developer's local `.data/` folder: it contains private cards,
seat tokens and profile records. A new hosted installation starts with its own
empty storage. Any deliberate data migration requires a separate reviewed step.

Free Render can sleep on inactivity; users may experience a cold start. Saved
rooms must restore after restart, and expired turn deadlines must still execute.

## Frontend

Create a separate Vercel project connected to this repository, Root Directory
`frontend`, framework Next.js. Configure `NEXT_PUBLIC_API_BASE_URL` to the Render
service's **HTTPS** URL, without a trailing slash. This value is embedded at build
time, so changing it requires a new frontend build.

The frontend uses HTTPS API requests and WSS room connections directly to Render.
After assigning a production frontend domain, configure the same exact origin in
`POKER_ROOM_ORIGINS` on Render. Avoid accepting arbitrary Vercel preview domains.

## Training sessions

AI tables are isolated by the anonymous saved training profile. Every `/api/hand/*`
request and saved decision requires that profile's bearer token. Browsers with
different profiles cannot read or mutate each other's live tables. Progress and
saved decisions are durable; an unfinished AI hand is in memory and resets on
server restart. Idle live tables may be reclaimed after 24 hours; the process caps
live training profiles at 1000. A browser's tabs intentionally share its profile.

## Release verification

1. Confirm HTTPS frontend, API health and all three interface languages.
2. Open two independent browser profiles: their AI hands and journals must differ.
3. Join a private room from two devices; verify private cards, WSS, turn clock,
   actions, reconnect and invitation links.
4. Restart the backend and confirm the room, archive and practice progress persist.
5. Confirm unknown profile/seat tokens cannot access another player's records.

Local test commands:

```sh
cd backend
.venv/bin/python -m unittest discover -s tests
cd ../frontend
npm run test:i18n
npm run build
```

No paid service or database should be provisioned until its plan is selected.

PostgreSQL integration checks use a separate disposable database, never the
production URL (the suite creates test profiles and rooms):

```sh
POKER_TEST_DATABASE_URL='<disposable PostgreSQL URI>' .venv/bin/python -m unittest discover -s tests -p test_postgres.py
```
