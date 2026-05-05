"""SQLite database setup and queries."""

import sqlite3
import os
from typing import Any

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "chess_arena.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leaderboard (
    id INTEGER PRIMARY KEY,
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    language TEXT NOT NULL,
    elo REAL DEFAULT 1200.0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    draws INTEGER DEFAULT 0,
    games INTEGER DEFAULT 0,
    illegal_moves INTEGER DEFAULT 0,
    UNIQUE(model_id, language)
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    white_model_id TEXT NOT NULL,
    white_language TEXT NOT NULL,
    black_model_id TEXT NOT NULL,
    black_language TEXT NOT NULL,
    mode TEXT NOT NULL,
    max_attempts INTEGER DEFAULT 2,
    result TEXT,
    result_reason TEXT,
    total_moves INTEGER DEFAULT 0,
    status TEXT DEFAULT 'playing',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS moves (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL,
    move_number INTEGER NOT NULL,
    color TEXT NOT NULL,
    move TEXT NOT NULL,
    move_icelandic TEXT,
    reasoning TEXT,
    was_retry INTEGER DEFAULT 0,
    illegal_reason TEXT,
    raw_response TEXT,
    FOREIGN KEY (game_id) REFERENCES games(id)
);
"""


def init_db(models: list[dict]) -> None:
    """Create tables and seed leaderboard rows for all model+language combos."""
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        # Migrations
        for col in ("illegal_reason TEXT", "first_attempt_move TEXT",
                    "first_attempt_raw_response TEXT", "first_attempt_prompt TEXT",
                    "eval_score TEXT", "attempts_made INTEGER DEFAULT 1",
                    "all_attempts TEXT"):
            try:
                conn.execute(f"ALTER TABLE moves ADD COLUMN {col}")
                conn.commit()
            except Exception:
                pass  # Column already exists
        for col in ("moves_win INTEGER DEFAULT 0",
                    "moves_loss INTEGER DEFAULT 0",
                    "moves_draw INTEGER DEFAULT 0",
                    "wins_as_white INTEGER DEFAULT 0",
                    "losses_as_white INTEGER DEFAULT 0",
                    "draws_as_white INTEGER DEFAULT 0",
                    "games_as_white INTEGER DEFAULT 0",
                    "wins_as_black INTEGER DEFAULT 0",
                    "losses_as_black INTEGER DEFAULT 0",
                    "draws_as_black INTEGER DEFAULT 0",
                    "games_as_black INTEGER DEFAULT 0",
                    "wins_by_checkmate INTEGER DEFAULT 0",
                    "losses_by_checkmate INTEGER DEFAULT 0",
                    "wins_by_forfeit INTEGER DEFAULT 0",
                    "losses_by_forfeit INTEGER DEFAULT 0",
                    "total_cp_loss INTEGER DEFAULT 0",
                    "cp_loss_moves INTEGER DEFAULT 0"):
            try:
                conn.execute(f"ALTER TABLE leaderboard ADD COLUMN {col}")
                conn.commit()
            except Exception:
                pass  # Column already exists
        for m in models:
            for lang in ("EN", "IS"):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO leaderboard
                        (model_id, model_name, language, elo, wins, losses, draws, games, illegal_moves)
                    VALUES (?, ?, ?, 1200.0, 0, 0, 0, 0, 0)
                    """,
                    (m["id"], m["name"], lang),
                )
        conn.commit()


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------

def create_game(
    white_model_id: str,
    white_language: str,
    black_model_id: str,
    black_language: str,
    mode: str,
    max_attempts: int = 2,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO games (white_model_id, white_language, black_model_id, black_language, mode, max_attempts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (white_model_id, white_language, black_model_id, black_language, mode, max_attempts),
        )
        conn.commit()
        return cur.lastrowid


def finish_game(game_id: int, result: str, result_reason: str, total_moves: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE games
            SET result=?, result_reason=?, total_moves=?, status='finished'
            WHERE id=?
            """,
            (result, result_reason, total_moves, game_id),
        )
        conn.commit()


def get_game(game_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        return dict(row) if row else None


def list_games() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM games ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Moves
# ---------------------------------------------------------------------------

def save_move(
    game_id: int,
    move_number: int,
    color: str,
    move: str,
    move_icelandic: str | None,
    reasoning: str | None,
    was_retry: bool,
    illegal_reason: str | None,
    raw_response: str | None,
    first_attempt_move: str | None = None,
    first_attempt_raw_response: str | None = None,
    first_attempt_prompt: str | None = None,
    eval_score: str | None = None,
    attempts_made: int = 1,
    all_attempts: list | None = None,
) -> None:
    import json
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO moves
                (game_id, move_number, color, move, move_icelandic, reasoning, was_retry,
                 illegal_reason, raw_response,
                 first_attempt_move, first_attempt_raw_response, first_attempt_prompt,
                 eval_score, attempts_made, all_attempts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id, move_number, color, move, move_icelandic, reasoning,
                1 if was_retry else 0, illegal_reason, raw_response,
                first_attempt_move, first_attempt_raw_response, first_attempt_prompt,
                eval_score, attempts_made,
                json.dumps(all_attempts) if all_attempts else None,
            ),
        )
        conn.commit()


def get_moves(game_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM moves WHERE game_id=? ORDER BY id ASC", (game_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def get_leaderboard(language: str = "all") -> list[dict]:
    with get_conn() as conn:
        if language.lower() == "all":
            rows = conn.execute(
                "SELECT * FROM leaderboard ORDER BY wins DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM leaderboard WHERE language=? ORDER BY wins DESC",
                (language.upper(),),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["avg_moves_per_game"] = round(
                (d.get("moves_win", 0) + d.get("moves_loss", 0) + d.get("moves_draw", 0)) / d["games"], 1
            ) if d["games"] else None
            d["avg_moves_win"] = round(d.get("moves_win", 0) / d["wins"], 1) if d["wins"] else None
            d["avg_moves_loss"] = round(d.get("moves_loss", 0) / d["losses"], 1) if d["losses"] else None
            d["wld_as_white"] = f'{d.get("wins_as_white",0)} / {d.get("losses_as_white",0)} / {d.get("draws_as_white",0)}' if d.get("games_as_white") else None
            d["wld_as_black"] = f'{d.get("wins_as_black",0)} / {d.get("losses_as_black",0)} / {d.get("draws_as_black",0)}' if d.get("games_as_black") else None
            d["illegal_per_game"] = round(d["illegal_moves"] / d["games"], 2) if d["games"] else None
            cp_moves = d.get("cp_loss_moves", 0)
            d["avg_cp_loss"] = round(d.get("total_cp_loss", 0) / cp_moves, 1) if cp_moves else None
            result.append(d)
        return result


def update_leaderboard(
    model_id: str,
    language: str,
    new_elo: float,
    result: str,          # "win", "loss", "draw"
    illegal_moves_delta: int,
    total_moves: int = 0,
    color: str = "",      # "white" or "black"
    result_reason: str = "",
    cp_loss: int = 0,
    cp_loss_moves: int = 0,
) -> None:
    with get_conn() as conn:
        win_delta = 1 if result == "win" else 0
        loss_delta = 1 if result == "loss" else 0
        draw_delta = 1 if result == "draw" else 0
        moves_win_delta = total_moves if result == "win" else 0
        moves_loss_delta = total_moves if result == "loss" else 0
        moves_draw_delta = total_moves if result == "draw" else 0
        wins_by_checkmate_delta  = 1 if (result == "win"  and result_reason == "checkmate") else 0
        losses_by_checkmate_delta = 1 if (result == "loss" and result_reason == "checkmate") else 0
        wins_by_forfeit_delta    = 1 if (result == "win"  and result_reason == "forfeit")   else 0
        losses_by_forfeit_delta  = 1 if (result == "loss" and result_reason == "forfeit")   else 0
        wins_as_white_delta   = 1 if (color == "white" and result == "win")  else 0
        losses_as_white_delta = 1 if (color == "white" and result == "loss") else 0
        draws_as_white_delta  = 1 if (color == "white" and result == "draw") else 0
        games_as_white_delta  = 1 if color == "white" else 0
        wins_as_black_delta   = 1 if (color == "black" and result == "win")  else 0
        losses_as_black_delta = 1 if (color == "black" and result == "loss") else 0
        draws_as_black_delta  = 1 if (color == "black" and result == "draw") else 0
        games_as_black_delta  = 1 if color == "black" else 0
        conn.execute(
            """
            UPDATE leaderboard
            SET elo=?,
                wins=wins+?,
                losses=losses+?,
                draws=draws+?,
                games=games+1,
                illegal_moves=illegal_moves+?,
                moves_win=moves_win+?,
                moves_loss=moves_loss+?,
                moves_draw=moves_draw+?,
                wins_as_white=wins_as_white+?,
                losses_as_white=losses_as_white+?,
                draws_as_white=draws_as_white+?,
                games_as_white=games_as_white+?,
                wins_as_black=wins_as_black+?,
                losses_as_black=losses_as_black+?,
                draws_as_black=draws_as_black+?,
                games_as_black=games_as_black+?,
                wins_by_checkmate=wins_by_checkmate+?,
                losses_by_checkmate=losses_by_checkmate+?,
                wins_by_forfeit=wins_by_forfeit+?,
                losses_by_forfeit=losses_by_forfeit+?,
                total_cp_loss=total_cp_loss+?,
                cp_loss_moves=cp_loss_moves+?
            WHERE model_id=? AND language=?
            """,
            (
                new_elo,
                win_delta, loss_delta, draw_delta,
                illegal_moves_delta,
                moves_win_delta, moves_loss_delta, moves_draw_delta,
                wins_as_white_delta, losses_as_white_delta, draws_as_white_delta, games_as_white_delta,
                wins_as_black_delta, losses_as_black_delta, draws_as_black_delta, games_as_black_delta,
                wins_by_checkmate_delta, losses_by_checkmate_delta,
                wins_by_forfeit_delta, losses_by_forfeit_delta,
                cp_loss, cp_loss_moves,
                model_id, language.upper(),
            ),
        )
        conn.commit()


def get_elo(model_id: str, language: str) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT elo FROM leaderboard WHERE model_id=? AND language=?",
            (model_id, language.upper()),
        ).fetchone()
        return row["elo"] if row else 1200.0
