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
code. "Close table" disconnects while keeping the seat available for reconnect.
"Leave room" releases membership and invalidates its token. Other participants
continue; the host role transfers when the host leaves.

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
  `start`, `action`, `sit_out`, `leave`, or `settings`. Sit-out adds a boolean `sit_out`.
  Settings adds `settings` with integer `starting_stack`, `small_blind`,
  `big_blind`, and `turn_seconds`. Only the host may change these before the
  first deal; changing settings clears readiness for everyone.
  Ready adds `ready`; action adds `hand_id`, `action` and an
  optional integer `amount`. The server derives player identity from the token.
- Accepted commands get an `ack`. Repeating the same ID and payload cannot repeat
  an action. The latest 128 IDs per member are retained; older commands fail the
  revision check. Reusing an ID with another payload is rejected.
- On reconnect, the client reuses its token and may resend the exact pending
  command. Stale commands return an error and the newest snapshot; choose again.

Each room serializes commands and broadcasts personalized snapshots in revision
order. Each hand owns its deck. Shuffling uses the operating system's randomness.
The AI training API does not access or manage room hands.

## Completed hand archive

The room sidebar contains **Your hand history**. It lists only completed hands
dealt to the authenticated seat, newest first, with net chips and pagination.
New arrivals and replacement occupants cannot read previous occupants' hands.
Leaving revokes the seat token, including its history access.

- `GET /api/rooms/{code}/history?limit=20&before=123` returns summaries and
  `next_cursor` (null at the end). Limit is 1-50; cursors are stable if new hands finish.
- `GET /api/rooms/{code}/history/{hand_id}` returns a private final snapshot and
  replay frames. Both endpoints require `Authorization: Bearer <seat token>`;
  the invitation code alone is insufficient. Live hands have no archive endpoint.
- History responses use `Cache-Control: private, no-store` and `Vary: Authorization`.

The review dialog opens at the final result. First/Previous/Next/Result and the
step selector show the table before each recorded action. Opponent cards remain
hidden in earlier frames, even when they were revealed at the final showdown.
Folded opponents stay hidden throughout, including hand-strength card lists.
No remaining deck or seat tokens are sent to the client.

Replay reconstructs original starting stacks from final stacks, contributions and
payouts, restores the recorded cards/board, and runs the betting engine. It checks
every action and the final board, contributions, stacks and payouts. Incompatible
records fall back to the saved final result with a notice, never an approximate replay.

Review facts include net chips, pots, payouts, actual call amount and your made
hand at the time. Heads-up call price is shown before future betting/rake;
multiway side-pot EV is omitted. This is factual review, not a solver grade.
Opening a review does not pause or modify the live table or its turn timer.

## Current limits and next work

One backend process serves up to 200 rooms, stored in SQLite. Do not use multiple
workers: live state and socket ownership still belong to one process.
Players may join between hands. Defaults: blinds 5/10, initial stack 1000,
30 seconds per turn. The host may configure these before the first hand.
Stack range: 100-1,000,000 and at least 20 BB; 1 <= SB < BB <= 20,000,
SB <= 10,000; turn time 10-120 seconds. Values must be exact integers.
Stacks below BB receive one initial-stack amount of virtual chips between hands.
Each turn uses the configured time,
including after disconnect. The server owns the deadline; reconnecting cannot
extend it. On timeout it checks if legal, otherwise folds, then enables sit-out.
Deadlines are checked with a monotonic clock; clients receive an epoch deadline
and server time to display a synchronized countdown. A background task processes
timeouts even when no client sends messages.

Sit-out takes effect immediately: remaining decisions in the current hand use
check/fold. Return is possible between hands. A sitting-out player is excluded
from the next deal and keeps their stack. Leaving uses the same automatic policy
for the remaining hand, revokes the seat token and transfers the host role. A
replacement may join once the hand ends, with a fresh identity and initial stack;
they cannot inherit the prior occupant's private cards. Existing stacks and the
clockwise button position are preserved when the roster changes.

## Persistence

The default database is `backend/.data/poker.sqlite3`, resolved relative to the
backend source, independently of the working directory. Override with
`POKER_DB_PATH`. The database directory is excluded from Git. File permissions are
owner-only (0600); snapshots contain private cards, the remaining deck and bearer
tokens. Do not publish the database or expose its folder as static assets.

Each accepted mutation commits the room snapshot, recent command IDs, an event
journal entry and (when complete) the final hand in one SQLite transaction, before
broadcast/ack. On write failure, in-memory state is restored and no ack is sent.
The client receives an error and can choose again. Completed-hand insertion is
idempotent, so another ready/leave command cannot duplicate a payout record.

Startup restores rooms, tokens, cards, deck order, stacks, settings, button and
turn deadline. Socket connections are fresh; saved invitation links restore the
same browser seat. Restart does not reset the turn clock: downtime counts, and an
expired deadline performs the normal check/fold and sit-out. An unsupported or
corrupt database fails startup rather than silently creating empty rooms.

The training `/api/hand` session is separate and still lives in memory.
Next: training improvements, mobile polish, database backup/room cleanup and hosting.

WebSocket Origin is restricted to http://localhost:3000 and http://127.0.0.1:3000.
Set `POKER_ROOM_ORIGINS` to a comma-separated list of exact origins for another
local port or a future HTTPS deployment. The frontend reads
`NEXT_PUBLIC_API_BASE_URL` at build time; HTTPS URLs produce WSS connections.

Friends on different networks need the hosting stage: HTTPS/WSS, backup/cleanup,
request limits and a real test from different devices/networks.
The current server listens on loopback only.
