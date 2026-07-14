# Poker AI Coach Frontend

Next.js frontend for testing the Texas Hold'em hand flow.

## Run

Start the backend first from `../backend`:

```bash
uvicorn app.main:app --reload
```

Then run the frontend:

```bash
npm install
npm run dev
```

The app uses `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` by default.
