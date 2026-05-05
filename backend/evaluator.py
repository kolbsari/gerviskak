"""Stockfish position evaluator."""

import asyncio
import chess
import chess.engine
from backend.config import STOCKFISH_PATH

_DEPTH = 12


def format_score(score: chess.engine.PovScore) -> str:
    """Convert a PovScore (from white's POV) to a display string."""
    white_score = score.white()
    if white_score.is_mate():
        m = white_score.mate()
        return f"M{m}" if m > 0 else f"-M{abs(m)}"
    cp = white_score.score()
    return f"{cp:+d}"


async def evaluate(board: chess.Board) -> str | None:
    """Return an eval string for the current board position, from white's POV."""
    try:
        transport, engine = await chess.engine.popen_uci(STOCKFISH_PATH)
        try:
            info = await engine.analyse(board, chess.engine.Limit(depth=_DEPTH))
            return format_score(info["score"])
        finally:
            await engine.quit()
    except Exception:
        return None
