"""Public Chess.com game ingestion, filtered to completed standard rapid games.

The public API is read-only. Only public PGNs are retrieved.
"""
from __future__ import annotations

import re
import requests

HEADERS = {
    "User-Agent": "ChessIntelligenceCoach/0.2 (personal educational game-analysis app)",
    "Accept": "application/json",
}


def fetch_chesscom_rapid(username: str, limit: int = 30, rated_only: bool = False,
                         session: requests.Session | None = None) -> str:
    """Return most recent `limit` standard rapid PGNs from the public archive.

    Archives are monthly and sorted oldest to newest. Games in monthly archives
    are similarly sorted by end time. Fetch backwards until enough matches.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,25}", username):
        raise ValueError("Enter a valid Chess.com username (3–25 letters, digits, _ or -).")
    if not 1 <= limit <= 500:
        raise ValueError("Game limit must be between 1 and 500.")
    http = session or requests
    base = f"https://api.chess.com/pub/player/{username.casefold()}"
    r = http.get(f"{base}/games/archives", headers=HEADERS, timeout=30)
    r.raise_for_status()
    archives = r.json().get("archives", [])
    results: list[str] = []
    seen: set[str] = set()
    for archive in reversed(archives):
        # Reject third-party archive URLs, even if a response is malformed.
        if not re.fullmatch(r"https://api\.chess\.com/pub/player/[A-Za-z0-9_-]+/games/\d{4}/\d{2}", archive):
            continue
        result = http.get(archive, headers=HEADERS, timeout=30)
        result.raise_for_status()
        games = result.json().get("games", [])
        for game in reversed(games):
            if game.get("time_class") != "rapid" or game.get("rules") != "chess":
                continue
            if rated_only and not game.get("rated", False):
                continue
            pgn = game.get("pgn")
            if not isinstance(pgn, str) or not pgn.strip():
                continue
            uid = game.get("url") or pgn
            if uid in seen:
                continue
            seen.add(uid)
            results.append(pgn)
            if len(results) == limit:
                return "\n\n".join(results)
    return "\n\n".join(results)
