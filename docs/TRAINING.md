# Saved decisions and practice

Open http://localhost:3000/practice or choose **Practice & decisions** at the AI
training table. The browser creates an anonymous saved profile and keeps its bearer
token in localStorage (`poker-training-profile`). This profile is separate from
private-room seats. Do not share its token; knowing a room invitation cannot access it.

## Exercises

- Call price: heads-up break-even equity, before further betting or rake.
  Call amount / (contestable current pot + call amount). Uncallable overbets are
  excluded. Answers within 0.5 percentage points are accepted for rounding.
- Legal actions: choose the exact set allowed by the central betting rules.
  These cover checks, calls, raises, stack limits and reopening rights. The
  prompt includes public turn history and raise context; answer data is omitted.

Each profile starts with standard and short-stack practice scenarios. Each recorded
AI-table decision adds a rules question and, when appropriate, a heads-up call-price
question. Multiway decisions do not receive a single-pot EV/price exercise.
The queue selects questions with a latest incorrect answer, then unseen questions,
then the oldest previously correct ones. Skip selects another question without
creating an attempt. Answers are checked and saved on the server.

Progress counts all unique attempts, correct attempts and questions whose latest
answer is correct. It is not a mastery rating or a strategy score. Repeating a
question incorrectly makes it due for review again.

## Saved AI decisions

The AI-table UI submits actions through `/api/training/decision` with a unique
command ID, expected hand ID and action-history length. Under the existing table
lock, the server validates the move on a copy, computes the coach analysis, then
commits the private pre-action snapshot, choice, review and new questions in one
SQLite transaction. Only after a successful commit does it replace live state.
A failed write cannot consume chips. Duplicate command IDs do not repeat moves;
stale table versions are rejected. The client reloads authoritative state after
an uncertain response. Legacy `/api/hand/action` remains unrecorded but now requires the same profile token.

Saved decisions include the analysis assumptions and whether the choice matched
the coach heuristic. A different choice is not automatically an error; a match
is not an optimal-play grade. The UI's legacy internal `optimal` verdict value
continues to be displayed as **matches coach**.

## Storage and access

Training tables use the same private SQLite file as rooms, on a separate connection
protected by a thread lock. Profile token hashes, decisions, questions and attempts
survive restarts. Question answers and hidden AI cards are not included in exercise
responses. A profile can read and answer only its own questions and journal.
Live AI training tables are isolated by the authenticated training profile.
Different profiles cannot read or mutate each other's live hand. Browser tabs with
the same profile intentionally share a table. Live hands remain in memory and
reset on server restart; saved journals and progress persist. Idle tables may
be reclaimed after 24 hours, with a process limit of 1000 live profiles.
Friend-room hands never generate training advice or these decision records.

The browser needs its saved token to reopen its progress. Clearing browser storage
creates a new profile; there is no account recovery or cross-device sync yet.

## API

- `POST /api/training/profiles`: create a profile; token is returned once.
- Other routes require `Authorization: Bearer <training token>` and return
  `Cache-Control: private, no-store` with `Vary: Authorization`.
- `POST /api/training/decision`: accepted live choice and saved review.
- `GET /api/training/decisions?before=<id>`: journal, 20 records per page.
- `GET /api/training/progress`: saved attempt and question counts.
- `GET /api/training/exercises/next?kind=call_price|legal_actions&exclude=<id>`.
- `GET /api/training/exercises/{question_id}`: an exercise from a saved decision.
- `POST /api/training/answers`: question ID, unique attempt ID, and either a numeric
  `percent` or an `actions` array. Duplicate identical attempts return the prior
  result without incrementing progress; changed payloads with the same ID fail.

SQLite writes include decision/question creation or answer/progress updates in
single transactions. Tests cover write failures, concurrency, replay guards,
short calls, raise reopening, profile isolation and restart recovery.
