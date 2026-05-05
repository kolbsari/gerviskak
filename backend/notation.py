"""
Icelandic <-> English chess notation converter.

English: K Q R B N (pawn = no letter)
Icelandic: K D H B R (pawn = no letter)

Critical mapping:
  English R (Rook) <-> Icelandic H (Hrókur)
  English N (Knight) <-> Icelandic R (Riddari)
  English Q (Queen) <-> Icelandic D (Drottning)
  B and K are identical in both languages.

FEN strings, castling (O-O, O-O-O) are NOT converted.
"""

import re


# Only the piece letters that differ between languages
_EN_TO_IS = {"N": "R", "Q": "D", "R": "H"}
_IS_TO_EN = {"R": "N", "D": "Q", "H": "R"}


def _convert_move(move: str, table: dict) -> str:
    """Convert a single SAN move using the given letter substitution table."""
    # Castling is universal - don't touch
    if move in ("O-O-O", "O-O"):
        return move

    # We need to replace:
    # 1. Leading piece letter (if present): e.g. "N" in "Nf3", "Q" in "Qxd5"
    # 2. Promotion piece after "=": e.g. "Q" in "e8=Q"
    # Square coordinates (a-h, 1-8) must NOT be replaced.

    result = list(move)
    i = 0

    # Replace leading piece letter (uppercase letter that is a piece, not a square file)
    if result and result[0] in table:
        result[0] = table[result[0]]

    # Replace promotion piece (after '=')
    eq_idx = move.find("=")
    if eq_idx != -1 and eq_idx + 1 < len(move):
        p = move[eq_idx + 1]
        if p in table:
            result[eq_idx + 1] = table[p]

    return "".join(result)


def _convert_movetext(text: str, table: dict) -> str:
    """
    Convert all moves in a move-list string (e.g. "1. e4 Nf6 2. d4 d5").
    Preserves move numbers, dots, spaces, and annotation characters.
    """
    # Token pattern: move numbers (1.), moves, and other tokens
    # We match SAN moves specifically to avoid touching non-move tokens
    san_pattern = re.compile(
        r'\b([KQRBNHD]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBNHDqrbnhd])?[+#]?'
        r'|O-O-O|O-O'
        r'|[KQRBNHD][a-h][1-8]x[a-h][1-8][+#]?'  # fully-qualified captures
        r')\b'
    )

    def replace_token(m):
        return _convert_move(m.group(0), table)

    return san_pattern.sub(replace_token, text)


def to_icelandic(text: str) -> str:
    """Convert English notation to Icelandic notation (single move or movetext)."""
    # Check if it looks like a single move (no spaces or just one token)
    stripped = text.strip()
    if " " not in stripped and "\n" not in stripped:
        return _convert_move(stripped, _EN_TO_IS)
    return _convert_movetext(text, _EN_TO_IS)


def to_english(text: str) -> str:
    """Convert Icelandic notation to English notation (single move or movetext)."""
    stripped = text.strip()
    if " " not in stripped and "\n" not in stripped:
        return _convert_move(stripped, _IS_TO_EN)
    return _convert_movetext(text, _IS_TO_EN)
