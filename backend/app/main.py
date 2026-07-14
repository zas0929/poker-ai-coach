from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.hand import router as hand_router

app = FastAPI(title="Poker AI Coach API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(hand_router, prefix="/api/hand", tags=["hand"])


@app.get("/")
def root():
    return {"status": "ok", "app": "Poker AI Coach"}
