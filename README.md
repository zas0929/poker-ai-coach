# Poker AI Coach

Texas Hold'em AI Coach is a poker training app inspired by the Chess AI Coach architecture: a deterministic analysis backend, a focused frontend table, and an AI coach panel that explains decisions in natural language.

The core idea is hybrid:

- Poker engine does the math: hand state, legal actions, hand evaluation, Monte Carlo equity, pot odds, EV, ranges, and decision recommendations.
- LLM coach explains the result: why a fold, call, bet, or raise makes sense in the current spot.

The LLM should not guess poker strategy directly. It receives structured analysis from the engine and turns it into clear coaching.

## Project Structure

```txt
poker-ai-coach/
  backend/
    app/
      api/
        hand.py
      models/
        poker.py
      services/
        poker_engine.py
      main.py
    requirements.txt

  frontend/
    app/
    components/
    hooks/
    services/
    types/
```

## MVP Plan

1. Heads-up Texas Hold'em hand flow.
2. Start a new hand with hero and AI opponent hole cards.
3. Track street, board, pot, stacks, blinds, current player, and action history.
4. Add player actions: fold, check, call, bet, raise.
5. Add hand evaluator and showdown resolution.
6. Add Monte Carlo equity against simple opponent ranges.
7. Add pot odds and EV calculations.
8. Add decision engine with recommended action and confidence.
9. Add LLM Explain Decision endpoint for Coach Panel.
10. Build a clean poker table UI with Coach Panel as the primary learning surface.

## Backend Start

Run from `backend/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Start a hand:

```bash
curl -X POST http://localhost:8000/api/hand/start
```

Analyze the hero decision:

```bash
curl http://localhost:8000/api/hand/analyze
```

Apply a player action:

```bash
curl -X POST http://localhost:8000/api/hand/action \
  -H "Content-Type: application/json" \
  -d '{"player_id":"hero","action":"call"}'
```

Advance after betting action is closed:

```bash
curl -X POST http://localhost:8000/api/hand/advance
```

Manual street endpoints are still available, but they only work after the current betting round is closed:

```bash
curl -X POST http://localhost:8000/api/hand/flop
curl -X POST http://localhost:8000/api/hand/turn
curl -X POST http://localhost:8000/api/hand/river
```

## Frontend Start

Run from `frontend/` after the backend is running:

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

The UI shows a hand result after fold or showdown, including winners, pot awarded, and each player's final hand category.
Villain actions are automated through `POST /api/hand/ai-action`, using the current decision engine recommendation.
