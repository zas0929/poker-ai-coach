import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.hand import router as hand_router
from app.api.rooms import router as room_router, store

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(store.run_timers())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Poker AI Coach API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(hand_router, prefix="/api/hand", tags=["hand"])
app.include_router(room_router, prefix="/api/rooms", tags=["rooms"])


@app.get("/")
def root():
    return {"status": "ok", "app": "Poker AI Coach"}
