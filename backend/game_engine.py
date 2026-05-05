"""Core game loop — orchestrates a full LLM vs LLM chess game."""

import re
import asyncio
import chess
import chess.pgn

from backend import database as db, llm_clients, prompts, notation, elo as elo_mod, evaluator


# ---------------------------------------------------------------------------
# Move parsing
# ---------------------------------------------------------------------------

_EN_MOVE_RE = re.compile(
    r"\b([KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBNqrbn])?[+#]?"
    r"|O-O-O|O-O)\b"
)

_IS_MOVE_RE = re.compile(
    r"\b([KDHBRkdhbr]?[a-h]?[1-8]?x?[a-h][1-8](?:=[DHRBdhrbKk])?[+#]?"
    r"|O-O-O|O-O)\b"
)


def _parse_response(response: str, language: str) -> tuple[str | None, str | None]:
    """
    Extract (move, reasoning) from an LLM response.
    Move is returned as-given (still needs notation conversion if IS).
    """
    lang = language.upper()
    move_key = "LEIKUR" if lang == "IS" else "MOVE"
    reason_key = "ÁSTÆÐA" if lang == "IS" else "REASON"

    move_raw = None
    reasoning = None

    for line in response.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith(move_key + ":") and move_raw is None:
            move_raw = stripped[len(move_key) + 1:].strip()
        if upper.startswith(reason_key.upper() + ":") and reasoning is None:
            reasoning = stripped[len(reason_key) + 1:].strip()

    # Grab first token only for the move
    if move_raw:
        move_raw = move_raw.split()[0].rstrip(".,;").strip()

    if not move_raw:
        # Fallback regex scan
        candidates = _EN_MOVE_RE.findall(response)
        move_raw = candidates[0] if candidates else None

    if not move_raw:
        return None, reasoning

    return move_raw, reasoning


def _build_move_history(board: chess.Board, language: str, mode: str) -> str:
    """Return the move history string suitable for the prompt."""
    if board.move_stack:
        game = chess.pgn.Game.from_board(board)
        exporter = chess.pgn.StringExporter(
            headers=False, variations=False, comments=False
        )
        movetext = game.accept(exporter).strip().rstrip(" *")
    else:
        movetext = ""

    return movetext


def _try_parse_legal(board: chess.Board, move_str: str | None) -> tuple[chess.Move | None, str | None]:
    """Try to parse move_str as a legal SAN or UCI move on the given board.
    Returns (move, illegal_reason). move is None if illegal, illegal_reason is None if legal."""
    if not move_str:
        return None, "No move was extracted from the response"
    # Try SAN
    try:
        move = board.parse_san(move_str)
        if move in board.legal_moves:
            return move, None
        return None, f"'{move_str}' is not legal in this position"
    except Exception:
        pass
    # Try UCI (e.g. e2e4)
    try:
        move = chess.Move.from_uci(move_str.lower())
        if move in board.legal_moves:
            return move, None
        return None, f"'{move_str}' is not legal in this position"
    except Exception:
        pass
    return None, f"'{move_str}' could not be parsed as valid chess notation"


# ---------------------------------------------------------------------------
# ACPL helpers
# ---------------------------------------------------------------------------

def _parse_eval(s: str | None) -> int | None:
    """Convert an eval string like '+120', '-45', 'M3', '-M2' to centipawns."""
    if not s:
        return None
    s = s.strip()
    try:
        if 'M' in s.upper():
            sign = -1 if s.startswith('-') else 1
            return sign * 30000
        return int(s)
    except ValueError:
        return None


def _compute_acpl(moves: list[dict], color: str) -> tuple[int, int]:
    """
    Returns (total_cp_loss, num_moves) for the given color from a move list.
    eval_score is from white's POV. Loss is capped at 1000 cp per move.
    """
    total_loss = 0
    count = 0
    prev_eval: int | None = 0  # starting position is 0

    for m in moves:
        ev = _parse_eval(m.get("eval_score"))
        if prev_eval is not None and ev is not None and m["color"] == color:
            if color == "white":
                loss = max(0, prev_eval - ev)
            else:
                loss = max(0, ev - prev_eval)
            total_loss += min(loss, 1000)  # cap blunders at 1000cp
            count += 1
        if ev is not None:
            prev_eval = ev
        elif m.get("eval_score") is not None:
            prev_eval = None  # unknown eval breaks the chain

    return total_loss, count


# ---------------------------------------------------------------------------
# Main game loop
# ---------------------------------------------------------------------------

async def play_game(
    white_model_id: str,
    white_language: str,
    black_model_id: str,
    black_language: str,
    mode: str,
    max_attempts: int = 2,
) -> int:
    """Create a new game record and run the full game. Returns game_id."""
    game_id = db.create_game(
        white_model_id, white_language, black_model_id, black_language, mode, max_attempts
    )
    await play_game_with_id(
        game_id, white_model_id, white_language,
        black_model_id, black_language, mode, max_attempts,
    )
    return game_id


async def play_game_with_id(
    game_id: int,
    white_model_id: str,
    white_language: str,
    black_model_id: str,
    black_language: str,
    mode: str,
    max_attempts: int = 2,
) -> None:
    """Run the game loop for a pre-created game record."""

    board = chess.Board()
    half_move = 0
    illegal_counts = {"white": 0, "black": 0}

    result: str | None = None
    result_reason: str | None = None

    # Persistent conversation threads — one per player
    white_messages: list[dict] = []
    black_messages: list[dict] = []
    last_white_san: str | None = None
    last_black_san: str | None = None

    while True:
        color = "white" if board.turn == chess.WHITE else "black"
        model_id = white_model_id if color == "white" else black_model_id
        language = white_language if color == "white" else black_language
        messages = white_messages if color == "white" else black_messages
        opponent_san = last_black_san if color == "white" else last_white_san

        if not messages:
            # First turn for this player — full setup prompt
            prompt = prompts.build_first_prompt(language, color, opponent_san)
        else:
            # Subsequent turns — just the opponent's last move
            prompt = prompts.build_continuation_prompt(language, opponent_san)

        messages.append({"role": "user", "content": prompt})

        # --- First attempt ---
        try:
            raw_response = await asyncio.wait_for(
                llm_clients.get_response(model_id, messages), timeout=60
            )
        except asyncio.TimeoutError:
            result = "black" if color == "white" else "white"
            result_reason = "timeout"
            break

        move_str, reasoning = _parse_response(raw_response, language)
        legal_move, illegal_reason = _try_parse_legal(board, move_str)
        was_retry = False
        first_attempt_move: str | None = None
        first_attempt_raw: str | None = None
        first_attempt_prompt_str: str | None = None
        all_attempts: list | None = None

        if legal_move is None:
            first_attempt_move = move_str
            first_attempt_raw = raw_response
            first_attempt_prompt_str = prompt
            illegal_counts[color] += 1

            retry_prompt = prompts.build_retry_prompt(language)
            timed_out = False
            attempts_made = 1
            all_attempts = [raw_response]  # collect every raw response

            for _ in range(max_attempts - 1):
                messages.append({"role": "assistant", "content": raw_response})
                messages.append({"role": "user", "content": retry_prompt})
                try:
                    raw_response = await asyncio.wait_for(
                        llm_clients.get_response(model_id, messages), timeout=60
                    )
                except asyncio.TimeoutError:
                    result = "black" if color == "white" else "white"
                    result_reason = "timeout"
                    timed_out = True
                    break
                attempts_made += 1
                all_attempts.append(raw_response)
                move_str, reasoning = _parse_response(raw_response, language)
                legal_move, illegal_reason = _try_parse_legal(board, move_str)
                if legal_move is not None:
                    was_retry = True
                    break
                illegal_counts[color] += 1

            if timed_out:
                break

            if legal_move is None:
                result = "black" if color == "white" else "white"
                result_reason = "forfeit"
                half_move += 1
                db.save_move(
                    game_id=game_id,
                    move_number=(half_move + 1) // 2,
                    color=color,
                    move=move_str or "(none)",
                    move_icelandic=None,
                    reasoning=reasoning,
                    was_retry=True,
                    illegal_reason=illegal_reason,
                    raw_response=raw_response,
                    first_attempt_move=first_attempt_move,
                    first_attempt_raw_response=first_attempt_raw,
                    first_attempt_prompt=first_attempt_prompt_str,
                    attempts_made=attempts_made,
                    all_attempts=all_attempts,
                )
                break

        # --- Capture SAN before push ---
        move_san_en = board.san(legal_move)
        move_icelandic = None

        # Append the valid response to the thread before pushing
        messages.append({"role": "assistant", "content": raw_response})

        board.push(legal_move)
        half_move += 1

        if color == "white":
            last_white_san = move_san_en
        else:
            last_black_san = move_san_en

        eval_score = await evaluator.evaluate(board)

        db.save_move(
            game_id=game_id,
            move_number=(half_move + 1) // 2,
            color=color,
            move=move_san_en,
            move_icelandic=move_icelandic,
            reasoning=reasoning,
            was_retry=was_retry,
            illegal_reason=None,
            raw_response=raw_response,
            first_attempt_move=first_attempt_move,
            first_attempt_raw_response=first_attempt_raw,
            first_attempt_prompt=first_attempt_prompt_str,
            eval_score=eval_score,
            all_attempts=all_attempts if all_attempts else None,
        )

        # --- Check end conditions ---
        if board.is_checkmate():
            result = "black" if board.turn == chess.WHITE else "white"
            result_reason = "checkmate"
            break
        elif board.is_stalemate():
            result = "draw"
            result_reason = "stalemate"
            break
        elif board.is_fifty_moves():
            result = "draw"
            result_reason = "draw_50move"
            break
        elif board.is_repetition(3):
            result = "draw"
            result_reason = "draw_repetition"
            break
        elif board.is_insufficient_material():
            result = "draw"
            result_reason = "draw_insufficient"
            break
        elif half_move >= 400:
            result = "draw"
            result_reason = "draw_max_moves"
            break

    # --- Finalize ---
    db.finish_game(game_id, result or "draw", result_reason or "unknown", half_move)
    all_moves = db.get_moves(game_id)
    _update_ratings(
        white_model_id, white_language,
        black_model_id, black_language,
        result,
        illegal_counts,
        half_move,
        result_reason or "",
        all_moves,
    )


def _update_ratings(
    white_id: str, white_lang: str,
    black_id: str, black_lang: str,
    result: str | None,
    illegal_counts: dict,
    total_moves: int = 0,
    result_reason: str = "",
    all_moves: list | None = None,
) -> None:
    white_elo = db.get_elo(white_id, white_lang)
    black_elo = db.get_elo(black_id, black_lang)

    score_white = 1.0 if result == "white" else (0.0 if result == "black" else 0.5)
    new_white, new_black = elo_mod.update_elo(white_elo, black_elo, score_white)

    white_result = "win" if result == "white" else ("loss" if result == "black" else "draw")
    black_result = "win" if result == "black" else ("loss" if result == "white" else "draw")

    moves = all_moves or []
    w_cp_loss, w_cp_moves = _compute_acpl(moves, "white")
    b_cp_loss, b_cp_moves = _compute_acpl(moves, "black")

    db.update_leaderboard(white_id, white_lang, new_white, white_result, illegal_counts["white"], total_moves, "white", result_reason, w_cp_loss, w_cp_moves)
    db.update_leaderboard(black_id, black_lang, new_black, black_result, illegal_counts["black"], total_moves, "black", result_reason, b_cp_loss, b_cp_moves)
