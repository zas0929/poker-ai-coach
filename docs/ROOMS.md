# Private rooms

Open http://localhost:3000/friends. Create a room, share the invitation, and bring
2-6 players. Everyone clicks "I'm ready"; the host deals. Streets advance on the
server. This is a local preview with virtual chips, not an internet deployment.

## Run and verify

Backend: `cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
Frontend: `cd frontend && npm run build -- --webpack && npm start -- --hostname 127.0.0.1 --port 3000`.

From backend: `.venv/bin/python -m unittest discover -s tests`.
With a running server: `.venv/bin/python tests/room_websocket_smoke.py`.
The smoke test defaults to http://127.0.0.1:8000; override with `POKER_TEST_API_BASE`.

For two test players in one browser, open `/friends` in a second tab and manually
enter the room code. Each tab keeps its seat in sessionStorage; localStorage is
the fallback when reopening an invitation. The invitation contains only the room
code. "Other room" disconnects while keeping the seat available for reconnect.

## Server protocol

- `POST /api/rooms` with `{ "name": "Roman" }` creates a room.
- `POST /api/rooms/{code}/join` with a name reserves the next available seat.
- These responses return `code`, `player_id` and a private bearer `token`.
- Connect to `WS /api/rooms/{code}/ws`; send `{ "token": "..." }` within 5 seconds.
  The token never appears in the URL or invitation.
- Server `state` messages contain `revision`, `viewer_id`, members and a private
  hand projection. Other players' hole cards are empty arrays. At showdown only
  non-folded hands are revealed. Hidden cards are also removed from hand results.
- Commands include unique `command_id`, current `revision`, and `kind`: `ready`,
  `start`, or `action`. Ready adds `ready`; action adds `hand_id`, `action` and an
  optional integer `amount`. The server derives player identity from the token.
- Accepted commands get an `ack`. Repeating the same ID and payload cannot repeat
  an action. The latest 128 IDs per member are retained; older commands fail the
  revision check. Reusing an ID with another payload is rejected.
- On reconnect, the client reuses its token and may resend the exact pending
  command. Stale commands return an error and the newest snapshot; choose again.

Each room serializes commands and broadcasts personalized snapshots in revision
order. Each hand owns its deck. Shuffling uses the operating system's randomness.
The AI training API does not access or manage room hands.

## Current limits and next work

One backend process stores up to 200 rooms in memory. Restarting clears all rooms,
seats and hands. Do not use multiple workers until shared persistence is added.
The roster is fixed after the first deal. Blinds are 5/10, initial stacks 1000.
Stacks below 10 receive 1000 virtual chips between hands. A disconnected player's
seat is reserved and their turn waits for reconnect. Timers, sit-out, leaving and
changing the roster belong to the next stage.

WebSocket Origin is restricted to http://localhost:3000 and http://127.0.0.1:3000.
Set `POKER_ROOM_ORIGINS` to a comma-separated list of exact origins for another
local port or a future HTTPS deployment. The frontend reads
`NEXT_PUBLIC_API_BASE_URL` at build time; HTTPS URLs produce WSS connections.

Friends on different networks need the hosting stage: HTTPS/WSS, persistence,
room lifecycle, request limits and a real test from different devices/networks.
The current server listens on loopback only.
