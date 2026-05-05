"""FastAPI server — API routes and static file serving."""

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend import database as db, game_engine
from backend.config import MODELS

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="LLM Chess Arena")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# Initialize database on startup
@app.on_event("startup")
async def startup():
    db.init_db(MODELS)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class StartGameRequest(BaseModel):
    white_model_id: str
    white_language: str
    black_model_id: str
    black_language: str
    mode: str  # "fen" or "pgn"
    max_attempts: int = 2


# ---------------------------------------------------------------------------
# Active games tracking (game_id -> asyncio.Task)
# ---------------------------------------------------------------------------

_active_tasks: dict[int, asyncio.Task] = {}


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.post("/api/game/start")
async def start_game(req: StartGameRequest):
    # Validate model IDs
    from backend.config import MODELS_BY_ID
    if req.white_model_id not in MODELS_BY_ID:
        raise HTTPException(400, f"Unknown model: {req.white_model_id}")
    if req.black_model_id not in MODELS_BY_ID:
        raise HTTPException(400, f"Unknown model: {req.black_model_id}")
    if req.white_language.upper() not in ("EN", "IS"):
        raise HTTPException(400, "language must be EN or IS")
    if req.black_language.upper() not in ("EN", "IS"):
        raise HTTPException(400, "language must be EN or IS")
    if req.mode.lower() not in ("fen", "pgn"):
        raise HTTPException(400, "mode must be fen or pgn")

    # Create the game record first so we can return the ID immediately.
    # The game loop (play_game_with_id) uses this existing record.
    game_id = db.create_game(
        req.white_model_id,
        req.white_language.upper(),
        req.black_model_id,
        req.black_language.upper(),
        req.mode.lower(),
        req.max_attempts,
    )

    # Run the game loop in the background
    task = asyncio.create_task(
        _run_game(
            game_id,
            req.white_model_id,
            req.white_language.upper(),
            req.black_model_id,
            req.black_language.upper(),
            req.mode.lower(),
            req.max_attempts,
        )
    )
    _active_tasks[game_id] = task

    return {"game_id": game_id}


async def _run_game(
    game_id: int,
    white_model_id: str,
    white_language: str,
    black_model_id: str,
    black_language: str,
    mode: str,
    max_attempts: int = 2,
) -> None:
    try:
        await game_engine.play_game_with_id(
            game_id,
            white_model_id,
            white_language,
            black_model_id,
            black_language,
            mode,
            max_attempts,
        )
    except Exception as e:
        # Mark game as finished with error
        db.finish_game(game_id, "draw", f"error: {e}", 0)
    finally:
        _active_tasks.pop(game_id, None)


@app.get("/api/game/{game_id}")
async def get_game(game_id: int):
    game = db.get_game(game_id)
    if not game:
        raise HTTPException(404, "Game not found")

    moves = db.get_moves(game_id)

    # Build FEN at each move (skip illegal/forfeited moves)
    import chess
    board = chess.Board()
    for m in moves:
        if not m.get("illegal_reason"):
            try:
                board.push_san(m["move"])
            except Exception:
                pass
        m["fen_after"] = board.fen()

    return {
        **game,
        "fen": board.fen(),
        "moves": moves,
    }


@app.delete("/api/game/{game_id}")
async def stop_game(game_id: int):
    task = _active_tasks.get(game_id)
    if task:
        task.cancel()
        _active_tasks.pop(game_id, None)
        db.finish_game(game_id, "draw", "aborted", 0)
        return {"status": "aborted"}
    raise HTTPException(404, "No active game with that ID")


@app.get("/api/leaderboard")
async def get_leaderboard(language: str = "all"):
    return db.get_leaderboard(language)


@app.get("/api/games")
async def list_games():
    return db.list_games()


@app.get("/api/game/{game_id}/moves")
async def get_game_moves(game_id: int):
    game = db.get_game(game_id)
    if not game:
        raise HTTPException(404, "Game not found")
    return db.get_moves(game_id)


@app.get("/api/models")
async def list_models():
    return MODELS


@app.get("/api/preview-prompt")
async def preview_prompt(language: str = "EN", mode: str = "fen"):
    from backend.prompts import build_first_prompt
    prompt = build_first_prompt(language=language.upper(), color="white")
    return {"prompt": prompt}


# ---------------------------------------------------------------------------
# Static files — serve frontend
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")
