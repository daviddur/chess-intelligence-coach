"""Evidence-based, deliberately cautious explanations of costly chess decisions.

The engine establishes that a choice is worse; a geometric feature alone does not
establish *why*. We distinguish supported tactical consequences from candidate
strategic themes and retain genuinely unexplained decisions for deeper review.
"""
from __future__ import annotations

from dataclasses import dataclass

import chess
import chess.engine

VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
          chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
HOME_MINORS = {
    chess.WHITE: {chess.B1, chess.G1, chess.C1, chess.F1},
    chess.BLACK: {chess.B8, chess.G8, chess.C8, chess.F8},
}


@dataclass
class Diagnosis:
    theme: str
    explanation: str
    confidence: str
    evidence: list[str]
    question: str


def _after(board: chess.Board, line: list[chess.Move]) -> tuple[chess.Board, list[chess.Move]]:
    copy = board.copy(stack=False)
    legal_line = []
    for move in line:
        if move not in copy.legal_moves:
            break
        copy.push(move)
        legal_line.append(move)
    return copy, legal_line


def _material(board: chess.Board, color: bool) -> int:
    return sum(VALUES[p.piece_type] * (1 if p.color == color else -1)
               for p in board.piece_map().values())


def _center_distance(square: int) -> float:
    return abs(chess.square_file(square) - 3.5) + abs(chess.square_rank(square) - 3.5)


def _is_outpost(board: chess.Board, move: chess.Move) -> bool:
    piece = board.piece_at(move.from_square)
    if not piece or piece.piece_type != chess.KNIGHT:
        return False
    color = board.turn
    rank = chess.square_rank(move.to_square)
    if not (rank >= 4 if color == chess.WHITE else rank <= 3):
        return False
    new = board.copy(stack=False)
    new.push(move)
    if not new.is_attacked_by(color, move.to_square):
        return False
    # Heuristic only: a useful outpost ideally can't be driven away by a pawn.
    return not any(p.piece_type == chess.PAWN and p.color != color
                   for s in new.attackers(not color, move.to_square)
                   if (p := new.piece_at(s)))


def _what_changed(board: chess.Board, played: chess.Move, best: chess.Move,
                  actual_pv: list[chess.Move], best_pv: list[chess.Move],
                  stage: str) -> Diagnosis:
    color = board.turn
    played_san, best_san = board.san(played), board.san(best)
    after_played = board.copy(stack=False)
    after_played.push(played)

    # Engine PV evidence: a material difference across its calculated lines.
    if best_pv and best_pv[0] == best:
        best_end, legal_best = _after(board, best_pv[:8])
        actual_end, legal_actual = _after(after_played, actual_pv[:7])
        if len(legal_best) >= 2 and len(legal_actual) >= 1:
            best_mat = _material(best_end, color)
            actual_mat = _material(actual_end, color)
            if actual_mat <= _material(board, color) - 2 and best_mat >= actual_mat + 2:
                return Diagnosis(
                    "Material loss in continuation",
                    "The engine's continuation after your move leaves you with substantially less material than its preferred continuation. The sequence of captures or exchanges needs attention.",
                    "Supported", [f"Played {played_san} rather than {best_san}.",
                                  f"Material balance at the ends of these short engine lines: played {actual_mat:+d}; preferred {best_mat:+d} (pawn=1)."],
                    "Which forcing captures or exchanges create the material difference?",
                )
            if best_mat >= _material(board, color) + 2 and best_mat >= actual_mat + 2:
                return Diagnosis(
                    "Missed material opportunity",
                    "Stockfish's preferred continuation can gain material that your move does not obtain in the sampled lines.",
                    "Supported", [f"Played {played_san}; suggested {best_san}.",
                                  f"Engine-line material balances: best {best_mat:+d}, played {actual_mat:+d}."],
                    "Which forcing move starts the material-winning sequence?",
                )

    # These are observable differences, not proof of causation. Mark as tentative.
    best_piece = board.piece_at(best.from_square)
    played_piece = board.piece_at(played.from_square)
    if stage == "Opening" and board.is_castling(best) and not board.is_castling(played):
        return Diagnosis(
            "King safety / castling (candidate)",
            "The engine prefers castling here. This may reflect king safety or the need to connect your rooks, but the continuation must be checked before treating that as the definitive reason.",
            "Candidate", [f"The engine suggests {best_san} instead of {played_san}.",
                          "Castling changes king placement and activates the rook."],
            "What threats to your king exist, and does castling address them safely?",
        )
    if (stage == "Opening" and best_piece and best_piece.piece_type in (chess.BISHOP, chess.KNIGHT)
            and best.from_square in HOME_MINORS[color]
            and not (played_piece and played_piece.piece_type in (chess.BISHOP, chess.KNIGHT)
                     and played.from_square in HOME_MINORS[color])):
        return Diagnosis(
            "Development / piece activity (candidate)",
            "The recommended move develops a minor piece from its starting square. Compare its new squares and targets with the move you chose; development alone isn't enough to prove the explanation.",
            "Candidate", [f"The engine favours {best_san}; you played {played_san}.",
                          "The suggested move brings a bishop or knight into play from its home square."],
            "Which useful squares and targets does the newly developed piece gain?",
        )
    if _is_outpost(board, best) and not _is_outpost(board, played):
        return Diagnosis(
            "Strong squares / knight outpost (candidate)",
            "The recommended knight move occupies an advanced, supported square that is not currently attacked by an enemy pawn. Investigate whether this outpost disrupts the opponent's plan.",
            "Candidate", [f"The engine prefers {best_san} to {played_san}.",
                          f"The knight arrives on {chess.square_name(best.to_square)}, a potentially strong square."],
            "Can your opponent challenge this knight, and what does it threaten from that square?",
        )
    if stage == "Endgame" and best_piece and best_piece.piece_type == chess.KING:
        best_delta = _center_distance(best.from_square) - _center_distance(best.to_square)
        played_delta = (_center_distance(played.from_square) - _center_distance(played.to_square)) if played_piece and played_piece.piece_type == chess.KING else -2
        if best_delta > 0 and best_delta > played_delta:
            return Diagnosis(
                "Endgame king activity (candidate)",
                "The recommended king move heads closer to the centre. Active kings are often decisive in endgames, but calculate pawn races and checks before accepting that as the cause.",
                "Candidate", [f"Preferred {best_san}; played {played_san}.",
                              "The recommended king move reduces distance from the central four squares."],
                "Which pawns or squares can your king reach sooner after the recommended move?",
            )
    if (best_piece and best_piece.piece_type == chess.PAWN
            and (board.is_capture(best) or best.to_square in (chess.D4, chess.E4, chess.D5, chess.E5))
            and not (played_piece and played_piece.piece_type == chess.PAWN and
                     (board.is_capture(played) or played.to_square in (chess.D4, chess.E4, chess.D5, chess.E5)))):
        return Diagnosis(
            "Pawn break / central play (candidate)",
            "Stockfish prefers a pawn action that changes the centre or captures. Study the resulting pawn structure and newly opened lines; the geometry is a clue, not a conclusive diagnosis.",
            "Candidate", [f"Suggested pawn move {best_san} rather than {played_san}.",
                          "The move changes central occupation or initiates a pawn capture."],
            "Which files, diagonals and squares become accessible after this pawn move?",
        )
    return Diagnosis(
        "Needs deeper investigation",
        "The evaluation changed, but the available engine variation and board signals don't establish a reliable tactical or strategic explanation. This is not evidence of a specific weakness.",
        "Unresolved", [f"The fast engine pass preferred {best_san} over {played_san}.",
                       "No convincing motif or consequence was confirmed."],
        "What is the opponent's strongest reply, and what changes after a deeper search?",
    )


def diagnose(board: chess.Board, played: chess.Move, best: chess.Move,
             best_pv: list[chess.Move], actual_pv: list[chess.Move],
             mate_before: bool, mate_after: bool, stage: str,
             motif_detector) -> Diagnosis:
    """Return a supported consequence, tentative learning theme, or uncertainty."""
    if mate_before and not mate_after:
        return Diagnosis("Missed forced mate", "The engine found a forced mate before your move, but not after it.",
                         "Supported", [f"Forced mate missed by choosing {board.san(played)}."],
                         "Which checks force the opponent's king into a mating net?")
    best_tags = motif_detector(board, best)
    if best_tags:
        motif = best_tags[0]
        return Diagnosis("Missed " + motif.lower(),
                         f"Stockfish recommends a move containing the geometry of {motif.lower()}. Check the continuation to see whether it is actually decisive.",
                         "Candidate", [f"Engine move {board.san(best)} produces a potential {motif.lower()} pattern."],
                         "What makes this pattern tactically effective rather than just visually attractive?")
    after_played = board.copy(stack=False)
    after_played.push(played)
    if actual_pv and actual_pv[0] in after_played.legal_moves:
        reply = actual_pv[0]
        reply_san = after_played.san(reply)
        resp_tags = motif_detector(after_played, reply)
        if resp_tags:
            return Diagnosis("Allowed " + resp_tags[0].lower(),
                             f"Stockfish's reply {reply_san} creates the geometry of {resp_tags[0].lower()}. Follow the line to see why it matters.",
                             "Candidate", [f"Opponent's engine reply: {reply_san}.",
                                           f"Potential pattern: {resp_tags[0]}"],
                             "Which of your pieces or squares can the opponent exploit after this reply?")
        victim = after_played.piece_at(reply.to_square)
        if (victim and victim.color == board.turn
                and victim.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
                and not after_played.is_attacked_by(board.turn, reply.to_square)):
            return Diagnosis("Allowed capture of an undefended piece",
                             f"The engine's immediate reply {reply_san} captures a piece with no friendly defender on its square.",
                             "Supported", [f"Opponent can play {reply_san} after your move.",
                                           "The captured piece was undefended."],
                             "What did your opponent's previous move threaten, and how could you save the piece?" )
    return _what_changed(board, played, best, actual_pv, best_pv, stage)


def investigate(finding: dict, engine_path: str, seconds: float = 1.5, threshold_cp: int = 135, motif_detector=None,
                phase_detector=None) -> dict:
    """Reanalyse one finding more deeply; never fabricate certainty."""
    if motif_detector is None or phase_detector is None:
        raise ValueError("The app must supply its motif and game-phase helpers")
    board = chess.Board(finding["fen"])
    played = chess.Move.from_uci(finding["played_uci"])
    if played not in board.legal_moves:
        raise ValueError("Saved played move is not legal in the original position")
    engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    try:
        before = engine.analyse(board, chess.engine.Limit(time=seconds))
        best_pv = before.get("pv", [])
        if not best_pv:
            raise ValueError("Engine did not return a principal variation")
        best = best_pv[0]
        before_score = before["score"].pov(board.turn)
        mate_before = before_score.is_mate() and before_score.mate() > 0
        after = board.copy(stack=False)
        after.push(played)
        after_info = engine.analyse(after, chess.engine.Limit(time=seconds))
        actual_pv = after_info.get("pv", [])
        after_score = after_info["score"].pov(board.turn)
        mate_after = after_score.is_mate() and after_score.mate() > 0
        best_cp = before_score.score(mate_score=100000)
        actual_cp = after_score.score(mate_score=100000)
        loss = max(0, max(-1500, min(1500, best_cp)) - max(-1500, min(1500, actual_cp)))
        if best == played or loss < threshold_cp:
            diag = Diagnosis(
                "Not confirmed by deeper search",
                "The slower engine check did not reproduce a mistake above the original threshold. The fast evaluation was likely unstable; do not count this as a demonstrated weakness.",
                "Revised", [f"Deeper engine's suggested move: {board.san(best)}.",
                            f"Rechecked loss: {loss} cp, below the {threshold_cp} cp screening threshold."],
                "How does the new engine continuation differ from the original screening line?",
            )
        else:
            diag = diagnose(board, played, best, best_pv, actual_pv, mate_before, mate_after,
                            phase_detector(board), motif_detector)
        return {
            "theme": diag.theme, "explanation": diag.explanation, "confidence": diag.confidence,
            "evidence": diag.evidence, "question": diag.question,
            "best": board.san(best), "best_uci": best.uci(), "loss_cp": loss,
            "principal_variation": _san_line(board, best_pv),
            "punishment_line": _san_line(after, actual_pv),
            "depth_before": before.get("depth"), "depth_after": after_info.get("depth"),
        }
    finally:
        engine.quit()


def _san_line(board: chess.Board, moves: list[chess.Move]) -> str:
    b = board.copy(stack=False)
    output = []
    for move in moves[:8]:
        if move not in b.legal_moves:
            break
        output.append(f"{b.fullmove_number}{'.' if b.turn else '...'}{b.san(move)}")
        b.push(move)
    return " ".join(output)
