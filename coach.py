"""Inspectable, position-grounded coaching signals.

These are chessboard facts and heuristic prompts, NOT claims to know the
player's intentions or fully explain Stockfish's evaluation.
"""
from __future__ import annotations

from collections import Counter
import chess

PV = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
      chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
START_MINORS = {
    chess.WHITE: (chess.B1, chess.G1, chess.C1, chess.F1),
    chess.BLACK: (chess.B8, chess.G8, chess.C8, chess.F8),
}
PHASE_CHECKLIST = {
    "Opening": [
        "Check immediate threats before following an opening principle.",
        "Count undeveloped minor pieces and consider king safety.",
        "Ask what your last pawn move weakened and which central squares you control.",
    ],
    "Middlegame": [
        "Start with checks, captures and forcing threats for both players.",
        "Compare king safety, piece activity and the weakest pawns or squares.",
        "Name both sides' plans before deciding which plan is more urgent.",
    ],
    "Endgame": [
        "Check king activity and immediate tactics before advancing pawns.",
        "Find passed pawns and calculate whether either king can stop them.",
        "Ask whether exchanging pieces or pawns changes the theoretical outcome.",
    ],
}


def _material(board: chess.Board, color: bool) -> int:
    return sum(PV[p.piece_type] for p in board.piece_map().values() if p.color == color)


def _undefended_nonpawns(board: chess.Board, color: bool) -> list[str]:
    """Enemy can attack this piece and no friendly piece currently defends it.

    Does not assert a piece can be legally or profitably captured.
    """
    out = []
    for square, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type in (chess.KING, chess.PAWN):
            continue
        if board.is_attacked_by(not color, square) and not board.is_attacked_by(color, square):
            out.append(f"{piece.symbol().upper()} on {chess.square_name(square)}")
    return out


def _pawn_structure(board: chess.Board, color: bool) -> tuple[list[str], list[str]]:
    files = Counter(chess.square_file(sq) for sq, p in board.piece_map().items()
                    if p.color == color and p.piece_type == chess.PAWN)
    doubled = [chess.FILE_NAMES[f] for f, n in sorted(files.items()) if n > 1]
    isolated = [chess.FILE_NAMES[f] for f in sorted(files) if f - 1 not in files and f + 1 not in files]
    return doubled, isolated


def position_evidence(board: chess.Board) -> list[dict]:
    """Return facts about the side to move, each paired with a useful question."""
    us = board.turn
    them = not us
    facts = []
    if board.is_check():
        facts.append({"topic": "Immediate danger", "fact": "Your king is in check.",
                      "question": "Which legal replies also improve your position?"})
    advantage = _material(board, us) - _material(board, them)
    facts.append({"topic": "Material", "fact": f"Material difference: {advantage:+d} points (pawn=1, bishop/knight=3, rook=5, queen=9).",
                  "question": "Should your plan involve trading, or is something more urgent?"})
    if board.fullmove_number <= 16:
        undeveloped = [chess.square_name(s) for s in START_MINORS[us]
                       if (p := board.piece_at(s)) and p.color == us and p.piece_type in (chess.BISHOP, chess.KNIGHT)]
        facts.append({"topic": "Development", "fact": f"Minor pieces still on starting squares: {', '.join(undeveloped) if undeveloped else 'none'}.",
                      "question": "Can you improve a piece without allowing a tactical threat?"})
        king = board.king(us)
        if king in (chess.E1, chess.E8):
            facts.append({"topic": "King placement", "fact": "Your king remains on its original square.",
                          "question": "Is castling possible and useful, or is another immediate issue more important?"})
    center = (chess.D4, chess.E4, chess.D5, chess.E5)
    occupied_center = [chess.square_name(sq) for sq in center
                       if (p := board.piece_at(sq)) and p.piece_type == chess.PAWN and p.color == us]
    facts.append({"topic": "Central pawns", "fact": "Your pawns occupying central squares: " +
                  (", ".join(occupied_center) if occupied_center else "none") + ".",
                  "question": "Which central squares can your pieces influence even without a pawn there?"})
    loose = _undefended_nonpawns(board, us)
    if loose:
        facts.append({"topic": "Possible tactical targets", "fact": "Your currently attacked, undefended pieces: " + ", ".join(loose) + ".",
                      "question": "Does your opponent have a forcing way to exploit one? Verify legal moves."})
    their_loose = _undefended_nonpawns(board, them)
    if their_loose:
        facts.append({"topic": "Possible opportunities", "fact": "Opponent's attacked, undefended pieces: " + ", ".join(their_loose) + ".",
                      "question": "Can you exploit one with a legal forcing sequence?"})
    doubled, isolated = _pawn_structure(board, us)
    if doubled:
        facts.append({"topic": "Pawn structure", "fact": "You have doubled pawns on the " + ", ".join(doubled) + "-file(s).",
                      "question": "Are these a weakness, or do they support useful open files and activity?"})
    if isolated:
        facts.append({"topic": "Pawn structure", "fact": "Isolated pawn files: " + ", ".join(isolated) + ".",
                      "question": "Can these pawns be attacked, or can they support activity?"})
    checks = [board.san(m) for m in board.legal_moves if board.gives_check(m)]
    if checks:
        facts.append({"topic": "Forcing moves", "fact": "Legal checks to calculate: " + ", ".join(checks[:6]) + ("…" if len(checks) > 6 else "") + ".",
                      "question": "Do any checks lead to a useful continuation, or are they just checks?"})
    return facts


def move_features(board: chess.Board, san_or_uci: str) -> list[str]:
    """Simple observable consequences of a candidate move."""
    try:
        move = board.parse_san(san_or_uci)
    except (ValueError, AssertionError):
        try:
            move = chess.Move.from_uci(san_or_uci)
        except ValueError:
            return []
    if move not in board.legal_moves:
        return []
    mover = board.turn
    source = board.piece_at(move.from_square)
    capture = board.is_capture(move)
    was_check = board.gives_check(move)
    next_board = board.copy(stack=False)
    next_board.push(move)
    props = []
    if was_check:
        props.append("gives check")
    if capture:
        props.append("captures a piece or pawn")
    if board.is_castling(move):
        props.append("castles")
    if source and source.piece_type in (chess.BISHOP, chess.KNIGHT) and move.from_square in START_MINORS[mover]:
        props.append("develops a minor piece from its starting square")
    if source and source.piece_type == chess.PAWN and move.to_square in (chess.D4, chess.D5, chess.E4, chess.E5):
        props.append("occupies a central square with a pawn")
    if next_board.is_checkmate():
        props.append("delivers checkmate")
    return props


def prompts_for_stage(stage: str) -> list[str]:
    return PHASE_CHECKLIST.get(stage, PHASE_CHECKLIST["Middlegame"])


def reflection_comparison(fen: str, played: str, better: str) -> dict:
    board = chess.Board(fen)
    return {"played_features": move_features(board, played),
            "better_features": move_features(board, better)}
