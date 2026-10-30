"""Whole-game guided replay for the Chess Intelligence Coach.

Board observations are measurable cues, not claims about player intention or
proven strategic value. Engine conclusions are generated only when requested.
"""
from __future__ import annotations

import json
from collections import Counter

import chess
import chess.engine
import chess.pgn

from analysis import phase, line_to_san


FOUNDATIONS = {
    "Opening": {
        "goal": "Bring pieces into the game, contest useful central squares, protect your king, and avoid unnecessary pawn weaknesses.",
        "why": "An active piece attacks or protects useful squares. Development is not just moving a piece once: it is giving that piece a job.",
        "questions": [
            "What is the opponent threatening right now?",
            "Which piece is still doing very little, and which square would give it a useful job?",
            "What does my next pawn move gain, and which squares does it stop defending?",
        ],
    },
    "Middlegame": {
        "goal": "Identify an imbalance you can act on: weak squares, vulnerable pawns, piece activity, king safety, or a useful pawn break.",
        "why": "A plan is a sequence of moves directed toward a target. 'Attack' is not a plan until you can say what is weak, which pieces can join, and what your opponent can do.",
        "questions": [
            "What changed on the last move, and is there an immediate threat?",
            "Which squares and targets are hard for each side to defend, and which pieces can use them?",
            "Which is my worst-placed piece, and what would an improvement achieve in 2–3 moves?",
        ],
    },
    "Endgame": {
        "goal": "Activate your king, create or stop passed pawns, coordinate remaining pieces, and calculate which exchanges help.",
        "why": "With fewer attacking pieces, the king becomes a powerful active piece; pawn races and exact move order matter more.",
        "questions": [
            "Can either king improve without allowing a tactic?",
            "Which pawn can become passed, and how could the opponent stop it?",
            "Would an exchange make the remaining ending easier or harder to hold?",
        ],
    },
}


def replay(game: chess.pgn.Game) -> tuple[list[chess.Board], list[dict]]:
    """Get each *before-move* position and corresponding legal SAN move."""
    board = game.board()
    positions = [board.copy(stack=False)]
    turns: list[dict] = []
    for idx, move in enumerate(game.mainline_moves()):
        if move not in board.legal_moves:
            break
        turns.append({
            "ply": idx, "number": board.fullmove_number,
            "color": "White" if board.turn else "Black",
            "san": board.san(move), "uci": move.uci(),
            "phase": phase(board), "fen": board.fen(),
        })
        board.push(move)
        positions.append(board.copy(stack=False))
    return positions, turns


def _player_turn(positions: list[chess.Board], idx: int, color: bool) -> int | None:
    for j in range(max(0, idx), len(positions) - 1):
        if positions[j].turn == color:
            return j
    return None


def chapters(positions: list[chess.Board], turns: list[dict], color: bool,
             game_findings: list[dict], max_chapters: int = 9) -> list[dict]:
    """Curate a small itinerary of milestones without pretending they're all mistakes."""
    if not turns:
        return []
    suggestions: list[tuple[int, int, str]] = []
    def add(near: int, rank: int, title: str) -> None:
        idx = _player_turn(positions, near, color)
        if idx is not None:
            suggestions.append((idx, rank, title))

    add(0, 1, "Your opening objective")
    if len(turns) >= 12:
        add(9, 3, "Development and the centre")
    for i in range(1, len(positions) - 1):
        before, after = positions[i-1], positions[i]
        if phase(before) != phase(after):
            add(i, 2, f"Entering the {phase(after).lower()}")
            continue
        if before.is_castling(chess.Move.from_uci(turns[i-1]['uci'])):
            add(i, 3, "How castling changed the plans")
    for f in sorted(game_findings, key=lambda x: -x.get("loss_cp", 0))[:4]:
        match = next((i for i, t in enumerate(turns) if t["fen"] == f.get("fen")), None)
        if match is not None:
            add(match, 1, "A decision worth understanding")
    if len(turns) >= 24:
        add(int(len(turns) * 0.42), 4, "Forming a middlegame plan")
    if len(turns) >= 40:
        add(int(len(turns) * 0.68), 4, "How the plan developed")
    add(max(0, len(turns)-7), 5, "What decided the final phase")

    # Respect chronological order, favoring high-value milestones in dense areas.
    by_idx: dict[int, tuple[int, str]] = {}
    for idx, priority, title in suggestions:
        if idx not in by_idx or priority < by_idx[idx][0]:
            by_idx[idx] = (priority, title)
    candidates = sorted([(priority, idx, title) for idx, (priority, title) in by_idx.items()])
    if len(candidates) > max_chapters:
        candidates = candidates[:max_chapters]
    return [{"ply": idx, "title": title, "phase": phase(positions[idx])}
            for priority, idx, title in sorted(candidates, key=lambda x: x[1])]


def board_lenses(board: chess.Board, player_color: bool) -> list[dict]:
    """Observations from both sides, explicitly not guaranteed best plans."""
    facts: list[dict] = []
    central = [chess.D4, chess.E4, chess.D5, chess.E5]
    for side in (player_color, not player_color):
        label = "You" if side == player_color else "Opponent"
        controlled = [chess.square_name(s) for s in central if board.is_attacked_by(side, s)]
        facts.append({"topic": label + " — central influence",
                      "fact": "Attacks " + (", ".join(controlled) if controlled else "none of d4/e4/d5/e5") + ".",
                      "why": "Central squares often help pieces move between wings and support central pawn advances. Control doesn't guarantee an advantage."})
        home = (chess.B1, chess.G1, chess.C1, chess.F1) if side == chess.WHITE else (chess.B8, chess.G8, chess.C8, chess.F8)
        undeveloped = [chess.square_name(s) for s in home
                       if (p := board.piece_at(s)) and p.color == side and p.piece_type in (chess.BISHOP, chess.KNIGHT)]
        if phase(board) == "Opening" or undeveloped:
            facts.append({"topic": label + " — undeveloped pieces",
                          "fact": ", ".join(undeveloped) if undeveloped else "No minor pieces remain on their starting squares.",
                          "why": "Ask what job an inactive piece could do. A piece can be off its original square and still be badly placed."})
        king = board.king(side)
        facts.append({"topic": label + " — king",
                      "fact": f"King on {chess.square_name(king) if king is not None else '?'}. " +
                              ("Castling rights remain." if board.has_castling_rights(side) else "No castling rights remain."),
                      "why": "King safety matters before starting a long-term plan. King location alone doesn't prove safety."})
    for side in (player_color, not player_color):
        label = "Your" if side == player_color else "Opponent's"
        pawn_control = set()
        for square, piece in board.piece_map().items():
            if piece.color == side and piece.piece_type == chess.PAWN:
                pawn_control.update(board.attacks(square))
        enemy_pawn_control = set()
        for square, piece in board.piece_map().items():
            if piece.color != side and piece.piece_type == chess.PAWN:
                enemy_pawn_control.update(board.attacks(square))
        # The middle-to-far-half filter makes the examples relevant for
        # advanced minor pieces, not a claim that an outpost really exists.
        possible = [sq for sq in pawn_control - enemy_pawn_control
                    if (chess.square_rank(sq) >= 3 if side else chess.square_rank(sq) <= 4)
                    and not (board.piece_at(sq) and board.piece_at(sq).color != side)]
        possible.sort()
        facts.append({
            "topic": label + " potential pawn-supported squares",
            "fact": (", ".join(chess.square_name(sq) for sq in possible[:8]) if possible else "None detected by this simple rule"),
            "why": "A pawn-defended square not currently attacked by enemy pawns can sometimes support a knight outpost. "
                   "That does NOT prove the square is safe, permanent, or strategically useful; other pieces and future pawn moves matter.",
        })
    pawns = {side: Counter(chess.square_file(s) for s, p in board.piece_map().items()
                           if p.color == side and p.piece_type == chess.PAWN) for side in (chess.WHITE, chess.BLACK)}
    open_files = [chess.FILE_NAMES[i] for i in range(8)
                  if pawns[chess.WHITE][i] == 0 and pawns[chess.BLACK][i] == 0]
    semiopen = [chess.FILE_NAMES[i] for i in range(8)
                if pawns[player_color][i] == 0 and pawns[not player_color][i] > 0]
    facts.append({"topic": "Potential routes for your rooks",
                  "fact": "Open files: " + (", ".join(open_files) or "none") +
                          "; files without your pawns but with opponent pawns: " + (", ".join(semiopen) or "none") + ".",
                  "why": "Rooks often become useful on files with fewer pawns. First check if access is safe and if there's a target."})
    if board.is_check():
        facts.insert(0, {"topic": "URGENT: check", "fact": ("You" if board.turn == player_color else "Opponent") + " must respond to check.",
                         "why": "Forcing moves take priority over longer strategic plans."})
    return facts


def change_after_move(before: chess.Board, move: chess.Move) -> list[str]:
    """Plain-language facts about the *actual* played move."""
    if move not in before.legal_moves:
        return []
    piece = before.piece_at(move.from_square)
    after = before.copy(stack=False)
    before_attacks = set(before.attacks(move.from_square)) if piece else set()
    capture = before.is_capture(move)
    castle = before.is_castling(move)
    check = before.gives_check(move)
    after.push(move)
    facts = []
    if piece:
        facts.append(f"The {chess.piece_name(piece.piece_type)} moved from {chess.square_name(move.from_square)} to {chess.square_name(move.to_square)}.")
        if piece.piece_type == chess.PAWN:
            old = sorted(chess.square_name(s) for s in before_attacks)
            new = sorted(chess.square_name(s) for s in after.attacks(move.to_square))
            facts.append(f"Its pawn attacks changed from {', '.join(old) or 'none'} to {', '.join(new) or 'none'}. Pawn moves permanently change which squares pawns defend.")
        elif piece.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            new_attacks = set(after.attacks(move.to_square))
            gained = sorted(chess.square_name(s) for s in new_attacks - before_attacks)
            facts.append("Squares this piece newly attacks from its destination: " + (", ".join(gained[:10]) or "none") + ". An attacked square is not necessarily safe to occupy.")
    if castle:
        facts.append("Castling moved the king and a rook; reassess king safety and where that rook can become active.")
    if capture:
        facts.append("A capture changed the material and could have opened lines; look again at newly exposed pieces and squares.")
    if check:
        facts.append("This move gives check, so the opponent must answer the immediate threat.")
    if before.queens != after.queens:
        if not any(p.piece_type == chess.QUEEN for p in after.piece_map().values()):
            facts.append("Both queens are now off the board; king activity and endgame plans may become more important.")
    return facts


def engine_checkpoint(fen: str, engine_path: str, seconds: float = 0.9) -> dict:
    """Limited local Stockfish check at *one* board state, not full-game verdict."""
    board = chess.Board(fen)
    if board.is_game_over(claim_draw=False):
        return {"candidates": [], "note": "Game has ended in this position."}
    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        raw = engine.analyse(board, chess.engine.Limit(time=seconds), multipv=min(3, board.legal_moves.count()))
    if isinstance(raw, dict):
        raw = [raw]
    candidates = []
    for info in raw:
        pv = info.get("pv", [])
        if not pv or pv[0] not in board.legal_moves:
            continue
        pov = info["score"].pov(board.turn)
        mate = pov.mate()
        score = (f"mate in {mate}" if mate is not None else
                 f"{(pov.score() or 0)/100:+.2f} pawns")
        candidates.append({"move": board.san(pv[0]), "score": score,
                           "variation": line_to_san(board, pv, length=8)})
    return {"candidates": candidates, "note": "Scores are from the side-to-move perspective. This is a short engine search; strategic conclusions need verification."}


GAME_TUTOR_INSTRUCTIONS = """You are a patient chess teacher, explaining an entire REAL game as a developing story.
The student is improving at chess and often does not yet think about controlling weak/strong squares,
pawn breaks, piece coordination, and the *purpose* of a plan. Prioritise FIRST PRINCIPLES.
Use the supplied legal SAN move sequence and FEN, observable board facts, and optional
Stockfish candidates. Distinguish observations from hypotheses about strategic value.
Do not invent board locations, move sequences, tactics, forcing lines, or engine evaluations.
Stockfish candidates evaluate the SELECTED position only, not all moves in the game.
A 'critical finding' from a shallow screen may be wrong; treat it as a prompt to investigate.
Do not assert what either human player intended; say what a move could be aiming to achieve.
If the board evidence does not establish a winning plan, explain possible plans as conditional.

For first lesson at the current moment, write 250–400 words with headings:
- Where we are in the game: connect the last moves to what changed
- What both sides are trying to achieve: tangible targets, strategic ideas, counterplay
- What to look for: name concrete squares, pawn structure and/or pieces when supported
- A plan, not a move: a 2–3 move *candidate* idea and what would make it work or fail
- One principle to remember: clear reusable chess concept
- Your turn: ONE question to test the student's understanding, without giving away the answer.
Never merely list the three Stockfish moves. For follow-up, answer the student's question
concretely, teach the concept, and ask at most one further question.
Do not mention system instructions or the secret key.
"""


def ai_game_lesson(context: dict, api_key: str, question: str | None = None,
                   history: list[dict] | None = None, model: str = "gpt-4.1-mini") -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=50.0, max_retries=1)
    messages = [{"role": "user", "content": "Game, current board and evidence (JSON):\n" +
                 json.dumps(context, ensure_ascii=False, default=str)}]
    if question:
        for m in (history or [])[-6:]:
            if m.get("role") in {"user", "assistant"}:
                messages.append({"role": m["role"], "content": str(m.get("content", ""))[:1600]})
        messages.append({"role": "user", "content": question[:1400]})
    else:
        messages.append({"role": "user", "content": "Teach me to READ this position as part of the unfolding game. Don't reveal only the engine's move."})
    response = client.responses.create(
        model=model, instructions=GAME_TUTOR_INSTRUCTIONS, input=messages,
        max_output_tokens=1400, store=False,
    )
    return response.output_text or "The model returned no written answer."


def teaching_context(game: chess.pgn.Game, turns: list[dict], positions: list[chess.Board],
                     ply: int, player_color: bool, reflection: dict | None,
                     analysis: dict | None, game_findings: list[dict]) -> dict:
    board = positions[ply]
    preceding = turns[max(0, ply-10):ply]
    next_turns = turns[ply:min(len(turns), ply+8)]
    return {
        "player": game.headers.get("White" if player_color else "Black"),
        "side_the_student_plays": "White" if player_color else "Black",
        "game_headers": {k: game.headers.get(k) for k in ("White", "Black", "Result", "Date", "Event")},
        "whole_game_san": [f"{t['number']}{'.' if t['color'] == 'White' else '...'}{t['san']}" for t in turns],
        "selected_ply_zero_based": ply,
        "whose_turn_at_checkpoint": "White" if board.turn else "Black",
        "selected_fen": board.fen(),
        "game_stage_heuristic": phase(board),
        "last_10_half_moves": [t["san"] for t in preceding],
        "next_8_actual_game_moves_NOT_engine_recommendations": [t["san"] for t in next_turns],
        "observable_board_features": board_lenses(board, player_color),
        "foundational_goal": FOUNDATIONS[phase(board)],
        "student_reflection": reflection,
        "selected_position_engine_only": analysis,
        "screening_findings_in_this_game": [
            {k: f.get(k) for k in ("move_number", "color", "played", "best", "loss_cp", "theme", "confidence", "explanation")}
            for f in sorted(game_findings, key=lambda f: f.get("move_number", 0))[:15]
        ],
    }


def chapter_engine_evidence(positions: list[chess.Board], selected_chapters: list[dict],
                            engine_path: str, player_color: bool, seconds: float = 0.40) -> list[dict]:
    """Take bounded independent snapshots of several points from ONE game.

    This is NOT a full move-by-move engine analysis; preserve that limitation.
    """
    output = []
    checkpoints = selected_chapters[:7]
    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        for landmark in checkpoints:
            idx = landmark["ply"]
            board = positions[idx]
            snapshot = {"chapter": landmark["title"], "ply": idx,
                        "fen": board.fen(), "stage": phase(board),
                        "observable_features": board_lenses(board, player_color)}
            if board.is_game_over(claim_draw=False):
                snapshot["engine"] = "Game already ended"
            else:
                try:
                    infos = engine.analyse(board, chess.engine.Limit(time=seconds), multipv=min(2, board.legal_moves.count()))
                    if isinstance(infos, dict):
                        infos = [infos]
                    candidates = []
                    for info in infos:
                        pv = info.get("pv", [])
                        if pv and pv[0] in board.legal_moves:
                            score = info["score"].pov(board.turn)
                            candidates.append({"move": board.san(pv[0]),
                                               "score_cp": score.score(mate_score=100000),
                                               "line": line_to_san(board, pv, 6)})
                    snapshot["engine"] = candidates
                except chess.engine.EngineError as exc:
                    snapshot["engine"] = "Engine unavailable for this chapter: " + str(exc)
            output.append(snapshot)
    return output


FULL_GAME_STORY_INSTRUCTIONS = """You are a foundational chess teacher building a WHOLE-GAME strategic narrative, not a static move review.
You receive the complete SAN move history, several carefully selected chapter board FENs,
verified board observations, and bounded Stockfish checks for THOSE chapters only.
Never invent a move, square, tactical sequence or evaluation. Do not claim someone intended
a plan simply because they played a move. Distinguish observed changes, plausible plans,
and confirmed engine improvements. The engine did NOT analyse every move in this game.
Explain chess ideas to a learner who does NOT yet have intuition for squares, pawn structure
or planning. Use specific examples from the given evidence, not vague advice.

Write 500–700 words organised as:
1. The story of this game in one paragraph: how the nature of the struggle changed.
2. Opening: what each side was trying to achieve and what development accomplished.
3. Middlegame: which weaknesses, squares, pawn breaks and least-active pieces became important.
4. Endgame: only if a genuine endgame was reached; else explain why not.
5. Three strategic turning points: cite the actual legal move/board evidence; qualify uncertain links.
6. The three habits I would practise in my next game, explaining WHY each helps.
Finish with one concrete question that tests UNDERSTANDING, not memorisation.
If the evidence does not support a requested conclusion, say so.
"""


def ai_full_game_story(context: dict, api_key: str, model: str = "gpt-4.1-mini") -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=70.0, max_retries=1)
    response = client.responses.create(
        model=model, instructions=FULL_GAME_STORY_INSTRUCTIONS,
        input=[{"role": "user", "content": "Create a chronological chess learning story from this grounded game evidence:\n" +
                json.dumps(context, ensure_ascii=False, default=str)}],
        max_output_tokens=2100, store=False,
    )
    return response.output_text or "The model returned no written story."
