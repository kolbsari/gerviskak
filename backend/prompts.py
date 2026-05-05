"""Prompt templates and builder for the chess arena."""

_EN_RETRY = "That move is illegal. Try again using standard algebraic notation (SAN), e.g. e4, Nf6, Bxc6, O-O.\nReply in this exact format (example: MOVE: e4):\nMOVE: <move>\nREASON: <one sentence explaining your reasoning>"
_IS_RETRY = "Þetta leikur er ólöglegur. Reyndu aftur. Notaðu staðlaða skáktáknun (SAN), t.d. e4, Nf6, Bxc6, O-O.\nSvaraðu á þessu sniði (dæmi: LEIKUR: e4):\nLEIKUR: <leikur>\nÁSTÆÐA: <ein setning sem útskýrir rökin þín>"


def build_first_prompt(language: str, color: str, opponent_move: str | None = None) -> str:
    """
    Opening message for a player's thread.
    Sets up role and format, then asks for the first move.
    opponent_move is None for white's first turn, or white's first SAN for black's first turn.
    """
    is_icelandic = language.upper() == "IS"

    if is_icelandic:
        color_label = "hvítur" if color == "white" else "svartur"
        intro = f"Þú ert að tefla sem {color_label}."
        reply_format = (
            "Notaðu staðlaða skáktáknun (SAN), t.d. e4, Nf6, Bxc6, O-O.\n"
            "Svaraðu á þessu sniði (dæmi: LEIKUR: e4):\n"
            "LEIKUR: <leikur>\nÁSTÆÐA: <ein setning sem útskýrir rökin þín>"
        )
        if opponent_move:
            question = f"Andstæðingurinn þinn hóf með {opponent_move}. Hvað er svar þitt?"
        else:
            question = "Hver er fyrsta leikurinn þinn?"
    else:
        color_label = color
        intro = f"You are playing chess as {color_label}."
        reply_format = (
            "Use standard algebraic notation (SAN), e.g. e4, Nf6, Bxc6, O-O.\n"
            "Reply in this exact format (example: MOVE: e4):\n"
            "MOVE: <move>\nREASON: <one sentence explaining your reasoning>"
        )
        if opponent_move:
            question = f"Your opponent opened with {opponent_move}. What is your response?"
        else:
            question = "What is your first move?"

    return "\n\n".join([intro, reply_format, question])


def build_continuation_prompt(language: str, opponent_move: str) -> str:
    """Short message for moves 2+ — just the opponent's last move."""
    if language.upper() == "IS":
        return f"Andstæðingurinn þinn lék {opponent_move}. Hver er næsti leikurinn þinn?"
    else:
        return f"Your opponent played {opponent_move}. What is your next move?"


def build_retry_prompt(language: str) -> str:
    """Return the illegal-move retry message in the correct language."""
    return _IS_RETRY if language.upper() == "IS" else _EN_RETRY
