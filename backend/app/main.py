import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from app.services.room_repository import RoomStorageError

from app.api.training import router as training_router, store as training_store, profile
from app.api.hand import router as hand_router, training_owner
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

@app.middleware('http')
async def private_training_table(request, call_next):
    path = request.url.path
    protected = path.startswith('/api/hand/') or path == '/api/training/decision'
    if not protected or request.method == 'OPTIONS':
        return await call_next(request)
    try:
        owner = await run_in_threadpool(profile, request.headers.get('authorization'))
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail}, headers={'Cache-Control': 'no-store'})
    binding = training_owner.set(owner)
    try:
        response = await call_next(request)
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Vary'] = 'Authorization'
        return response
    finally:
        training_owner.reset(binding)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[value.strip() for value in os.environ.get(
        'POKER_ROOM_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000'
    ).split(',') if value.strip()],
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
