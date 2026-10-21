import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.services.room_repository import RoomStorageError

from app.api.training import router as training_router, store as training_store
from app.api.hand import router as hand_router
from app.api.rooms import router as room_router, store

@asynccontextmanager
async def lifespan(app):
    store.open()
    training_store.open()
    task = asyncio.create_task(store.run_timers())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        training_store.close()
        store.close()


app = FastAPI(title="Poker AI Coach API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(training_router, prefix="/api/training", tags=["training"])
app.include_router(hand_router, prefix="/api/hand", tags=["hand"])
app.include_router(room_router, prefix="/api/rooms", tags=["rooms"])


@app.get("/")
def root():
    return {"status": "ok", "app": "Poker AI Coach"}


@app.exception_handler(RoomStorageError)
async def storage_error(request, exc):
    return JSONResponse(status_code=503, content={'detail': str(exc)})
