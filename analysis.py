"""Chess Pattern Coach: PGN ingestion and conservative Stockfish motif analysis.

Motif labels are geometric heuristics attached to engine-confirmed evaluation
losses, not a claim that we can prove every tactical theme in every position.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
import io
import re
from typing import Callable, Iterable

import chess
import chess.engine
import chess.pgn
import requests
from collector import fetch_chesscom_rapid

HEADERS = {
    "User-Agent": "ChessPatternCoach/0.1 (educational personal game analysis; contact via app owner)",
    "Accept": "application/json, application/x-chess-pgn, text/plain",
}
PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


@dataclass
class Finding:
    game: int
    game_url: str
    date: str
    time_control: str
    color: str
    move_number: int
    stage: str
    fen: str
    played: str
    played_uci: str
    best: str
    best_uci: str
    principal_variation: str
    punishment_line: str
    loss_cp: int
    severity: str
    theme: str
    explanation: str


def fetch_chesscom(username: str, limit: int) -> str:
    """Load the most recent standard Chess.com RAPID games only."""
    return fetch_chesscom_rapid(username, limit=limit)


def fetch_lichess(username: str, limit: int) -> str:
    url = f"https://lichess.org/api/games/user/{username}"
    r = requests.get(url, params={"max": limit, "sort": "dateDesc", "pgnInJson": "false", "clocks": "false"},
                     headers={**HEADERS, "Accept": "application/x-chess-pgn"}, timeout=90)
    r.raise_for_status()
    return r.text


def parse_games(content: str, max_games: int) -> list[chess.pgn.Game]:
    stream = io.StringIO(content)
    games = []
    while len(games) < max_games:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        if game.errors:
            continue
        if game.headers.get("Variant", "Standard").lower() not in ("standard", "chess"):
            continue
        games.append(game)
    return games


def piece_targets(board: chess.Board, square: int, mover: bool) -> list[tuple[int, chess.Piece]]:
    return [(s, board.piece_at(s)) for s in board.attacks(square)
            if board.piece_at(s) and board.piece_at(s).color != mover]


def makes_skewer(board: chess.Board, square: int, mover: bool) -> bool:
    piece = board.piece_at(square)
    if not piece or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        return False
    directions = []
    if piece.piece_type in (chess.ROOK, chess.QUEEN):
        directions += [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if piece.piece_type in (chess.BISHOP, chess.QUEEN):
        directions += [(1, 1), (-1, 1), (1, -1), (-1, -1)]
    sf, sr = chess.square_file(square), chess.square_rank(square)
    for df, dr in directions:
        seen = []
        x, y = sf + df, sr + dr
        while 0 <= x < 8 and 0 <= y < 8:
            target = board.piece_at(chess.square(x, y))
            if target:
                if target.color == mover:
                    break
                seen.append(target)
                if len(seen) == 2:
                    if PIECE_VALUES[seen[0].piece_type] > PIECE_VALUES[seen[1].piece_type]:
                        return True
                    break
            x += df
            y += dr
    return False


def motifs_for_move(board: chess.Board, move: chess.Move) -> list[str]:
    """Conservative structural motif candidates for a legal move."""
    if move not in board.legal_moves:
        return []
    mover = board.turn
    captured = board.piece_at(move.to_square)
    before_pins = {s for s, piece in board.piece_map().items()
                   if piece.color != mover and piece.piece_type != chess.KING
                   and board.is_pinned(not mover, s)}
    # Remember pre-move line-piece attacks on valuable enemy targets.
    before_discoveries = {}
    for sq, p in board.piece_map().items():
        if p.color != mover and p.piece_type in (chess.ROOK, chess.QUEEN, chess.KING):
            before_discoveries[sq] = {a for a in board.attackers(mover, sq)
                                     if board.piece_at(a) and board.piece_at(a).piece_type
                                     in (chess.BISHOP, chess.ROOK, chess.QUEEN)}
    after = board.copy(stack=False)
    after.push(move)
    moved = after.piece_at(move.to_square)
    if not moved:
        return []
    tags = []
    if after.is_checkmate():
        tags.append("Mating combinations")
        king = after.king(not mover)
        if king is not None and chess.square_rank(king) == (7 if mover else 0) and moved.piece_type in (chess.ROOK, chess.QUEEN):
            tags.insert(0, "Back-rank mates")
    if moved.piece_type in (chess.KNIGHT, chess.PAWN, chess.QUEEN, chess.BISHOP, chess.ROOK):
        targets = [(sq, p) for sq, p in piece_targets(after, move.to_square, mover)
                   if p.piece_type != chess.PAWN]
        if len(targets) >= 2 and any(p.piece_type in (chess.KING, chess.QUEEN, chess.ROOK) for _, p in targets):
            tags.append("Forks / double attacks")
    new_pins = {sq for sq, p in after.piece_map().items()
                if p.color != mover and p.piece_type != chess.KING
                and after.is_pinned(not mover, sq)}
    if new_pins - before_pins:
        tags.append("Pins")
    if makes_skewer(after, move.to_square, mover):
        tags.append("Skewers")
    for target, old_attackers in before_discoveries.items():
        p = after.piece_at(target)
        if not p or p.color == mover:
            continue
        new_attackers = {a for a in after.attackers(mover, target)
                         if after.piece_at(a) and after.piece_at(a).piece_type
                         in (chess.BISHOP, chess.ROOK, chess.QUEEN)}
        if any(a != move.to_square for a in (new_attackers - old_attackers)):
            tags.append("Discovered attacks")
            break
    # Only label a free capture when an enemy non-pawn piece is capturable,
    # the captured square was not defended and the engine confirms the loss.
    if captured and captured.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        if not board.is_attacked_by(not mover, move.to_square):
            tags.append("Undefended pieces")
    return list(dict.fromkeys(tags))


def classify(board: chess.Board, played: chess.Move, best: chess.Move, pv: list[chess.Move],
             mate_before: bool, mate_after: bool) -> tuple[str, str]:
    tags = motifs_for_move(board, best)
    if mate_before and not mate_after:
        return "Missed forced mates", "The engine found a forced mate before your move, but it was lost after your move."
    if tags:
        return "Missed " + tags[0].lower(), "The engine's preferred continuation features " + tags[0].lower() + "."
    after = board.copy(stack=False)
    after.push(played)
    if pv:
        # Best opponent reply to the actual played move, not to the engine's best move.
        response = pv[0]
        if response in after.legal_moves:
            response_tags = motifs_for_move(after, response)
            if response_tags:
                return "Allowed " + response_tags[0].lower(), "Your move allowed an opponent continuation featuring " + response_tags[0].lower() + "."
            victim = after.piece_at(response.to_square)
            if victim and victim.color == board.turn and victim.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
                if not after.is_attacked_by(board.turn, response.to_square):
                    return "Left pieces hanging", "The engine's reply captures one of your undefended pieces."
    return "Other evaluation losses", "The evaluation dropped, but no tactical motif was confirmed by the first-pass pattern rules."


def engine_cp(info: dict, pov: bool) -> int | None:
    score = info.get("score")
    if score is None:
        return None
    n = score.pov(pov).score(mate_score=100000)
    return max(-1500, min(1500, n)) if n is not None else None


def phase(board: chess.Board) -> str:
    if board.fullmove_number <= 12:
        return "Opening"
    if sum(1 for p in board.piece_map().values() if p.piece_type == chess.QUEEN) == 0 or len(board.piece_map()) <= 12:
        return "Endgame"
    return "Middlegame"


def line_to_san(board: chess.Board, pv: list[chess.Move], length: int = 5) -> str:
    b = board.copy(stack=False)
    out = []
    for m in pv[:length]:
        if m not in b.legal_moves:
            break
        out.append(f"{b.fullmove_number}{'.' if b.turn else '...'}{b.san(m)}")
        b.push(m)
    return " ".join(out)


def scan_games(
    games: Iterable[chess.pgn.Game], username: str, engine_path: str,
    seconds_per_position: float = 0.08, threshold_cp: int = 135,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    parsed_games = list(games)
    results: list[Finding] = []
    motif_events = Counter()
    motif_missed = Counter()
    total_positions = 0
    games_used = 0
    engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    try:
        for game_number, game in enumerate(parsed_games, 1):
            headers = game.headers
            white = headers.get("White", "").casefold()
            black = headers.get("Black", "").casefold()
            if username.casefold() not in (white, black):
                if progress:
                    progress(game_number, len(parsed_games))
                continue
            user_color = white == username.casefold()
            board = game.board()
            if board.chess960 or board.uci_variant != "chess":
                continue
            game_has_player_move = False
            for move in game.mainline_moves():
                if move not in board.legal_moves:
                    break
                if board.turn != user_color:
                    board.push(move)
                    continue
                game_has_player_move = True
                total_positions += 1
                move_number = board.fullmove_number
                curr_phase = phase(board)
                fen = board.fen()
                played_san = board.san(move)
                before = engine.analyse(board, chess.engine.Limit(time=seconds_per_position))
                best_line = before.get("pv", [])
                if not best_line:
                    board.push(move)
                    continue
                best = best_line[0]
                best_san = board.san(best)
                tags = motifs_for_move(board, best)
                for tag in tags:
                    motif_events[tag] += 1
                if best == move:
                    board.push(move)
                    continue
                best_cp = engine_cp(before, user_color)
                mate_before = before["score"].pov(user_color).is_mate() and before["score"].pov(user_color).mate() > 0
                board.push(move)
                after = engine.analyse(board, chess.engine.Limit(time=seconds_per_position))
                actual_cp = engine_cp(after, user_color)
                if best_cp is None or actual_cp is None:
                    continue
                loss = max(0, best_cp - actual_cp)
                if loss < threshold_cp:
                    continue
                actual_response = after.get("pv", [])
                mate_after = after["score"].pov(user_color).is_mate() and after["score"].pov(user_color).mate() > 0
                # Supply the BEFORE-move position, the engine's best move, and
                # the opponent's response to the actual move for classification.
                orig = chess.Board(fen)
                theme, explanation = classify(orig, move, best, actual_response, mate_before, mate_after)
                for tag in tags:
                    motif_missed[tag] += 1
                severity = "Blunder" if loss >= 300 else "Mistake" if loss >= 170 else "Inaccuracy"
                results.append(Finding(
                    game=game_number, game_url=headers.get("Link", headers.get("Site", "")),
                    date=headers.get("Date", "Unknown"),
                    time_control=headers.get("TimeControl", "Unknown"),
                    color="White" if user_color else "Black", move_number=move_number,
                    stage=curr_phase, fen=fen, played=played_san, played_uci=move.uci(),
                    best=best_san, best_uci=best.uci(),
                    principal_variation=line_to_san(orig, best_line),
                    punishment_line=line_to_san(board, actual_response),
                    loss_cp=loss, severity=severity, theme=theme,
                    explanation=explanation,
                ))
            if game_has_player_move:
                games_used += 1
            if progress:
                progress(game_number, len(parsed_games))
    finally:
        engine.quit()
    return {
        "games": games_used, "positions": total_positions,
        "findings": [asdict(f) for f in sorted(results, key=lambda f: f.loss_cp, reverse=True)],
        "motif_events": dict(motif_events), "motif_missed": dict(motif_missed),
    }
