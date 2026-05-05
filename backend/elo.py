"""Elo rating calculation. K-factor = 32, starting Elo = 1200."""


def update_elo(
    rating_a: float, rating_b: float, score_a: float, k: int = 32
) -> tuple[float, float]:
    """
    Compute new Elo ratings for both players after a game.

    score_a: 1.0 = A wins, 0.5 = draw, 0.0 = A loses
    Returns (new_rating_a, new_rating_b).
    """
    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    expected_b = 1 - expected_a

    score_b = 1.0 - score_a

    new_a = rating_a + k * (score_a - expected_a)
    new_b = rating_b + k * (score_b - expected_b)

    return round(new_a, 2), round(new_b, 2)
