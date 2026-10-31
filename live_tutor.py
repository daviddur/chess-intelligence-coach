"""Conversational, engine-grounded chess coach for a single unfolding game.

Text, turn-by-turn microphone input, and optional speech output are supported.
Chess calculations are performed by python-chess/Stockfish, not the LLM.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import chess
import chess.svg
import streamlit as st
from openai import OpenAI

from analysis import parse_games, phase
from game_coach import replay, chapters, board_lenses, change_after_move, engine_checkpoint


TUTOR_RULES = """You are an engaged, knowledgeable private chess teacher guiding ONE student's REAL game.
You are a conversational coach, not a textbook or a generic engine commentator.
You are talking to a roughly beginner/intermediate learner who wants foundations of positional understanding.
The learner specifically wants to understand WHAT TO ACHIEVE, WHY squares/structure matter,
and HOW to choose plans in a changing game—not static best-move trivia.

CONVERSATIONAL METHOD:
- In START or CHAPTER tasks, use the current position and recent moves and ask ONE purposeful
  question about a move the student played, their understanding of the position or the strategic plan.
  Start with a specific reference to their actual game and a concrete square/piece/decision.
- In REPLY tasks, FIRST address the learner's actual reasoning. Correct misconceptions tactfully
  and concretely. Teach ONE transferable idea; explain how to apply it to this exact board,
  describe a plausible plan for BOTH sides, and ask at most ONE targeted follow-up question.
- If they say 'I don't know', do not interrogate: teach using a short concrete example, then ask
  an easier choice or question. If they are right, deepen the reasoning rather than repeat praise.
- In PLAN tasks, give ONE plausible 2–3 move OBJECTIVE (not invented forced line), prerequisites,
  the opponent's likely COUNTERPLAN, and which board cues would change the plan.
- If learner asks directly about any topic, ANSWER IT rather than forcing a scripted question.
- Prefer 55–120 words per response, plain spoken English, 1 short paragraph or 2 brief paragraphs.
  No multi-section reports, bulleted encyclopaedias or repeated five-item checklists.
- Do not lead with Stockfish moves or numerical scores. Hold engine-best moves back while
  assessing the student's thinking; reveal when explicitly requested or when clarifying a mistake.
- Relate the current position to the previous conversation. Never repeat earlier lesson paragraphs.

TRUTH AND LIMITS:
- Supplied FEN, previous SANs, legal candidate moves and observable board features are evidence.
  Do not invent any move sequence, piece locations, knight control squares, evaluation or threat.
- Engine candidates are ONLY short-depth checks at this checkpoint, not proof of a strategy.
  A move's probable plan is a hypothesis, not knowledge of the human's intention.
- The student's upcoming HISTORICAL move is factual but not necessarily a good move.
- Do not assume unstated intent. Draw out the student's own rationale and acknowledge uncertainty.
- Never reveal future historical game moves beyond the single supplied student move.
- No secrets or private configuration in the response.
"""


def game_key(raw_pgn: str, game_number: int) -> str:
    return hashlib.sha256((hashlib.sha256(raw_pgn.encode()).hexdigest() + f":{game_number}").encode()).hexdigest()[:16]


def make_context(game: Any, positions: list, turns: list[dict], ply: int,
                 student_white: bool, engine: dict | None, chapter: str) -> dict:
    board = positions[ply]
    previous = turns[max(0, ply - 12):ply]
    next_move = turns[ply] if ply < len(turns) and board.turn == student_white else None
    recent_move = turns[ply-1] if ply > 0 else None
    return {
        "student_side": "White" if student_white else "Black",
        "opponent": game.headers.get("Black" if student_white else "White"),
        "current_game_stage_approx": phase(board),
        "checkpoint_name": chapter,
        "ply": ply,
        "fen": board.fen(),
        "side_to_move": "White" if board.turn else "Black",
        "recent_actual_moves": [f"{t['number']}{'.' if t['color']=='White' else '...'}{t['san']}" for t in previous],
        "last_played_move": (f"{recent_move['number']}{'.' if recent_move['color']=='White' else '...'}{recent_move['san']}" if recent_move else None),
        "student_next_actual_historical_move_to_discuss_not_the_best_move": (
            f"{next_move['number']}{'.' if next_move['color']=='White' else '...'}{next_move['san']}" if next_move else None
        ),
        "observable_board_facts_not_conclusions": [
            {"topic": v["topic"], "fact": v["fact"]} for v in board_lenses(board, student_white)[:9]
        ],
        "actual_last_move_effects": (
            change_after_move(positions[ply-1], chess.Move.from_uci(recent_move["uci"]))[:5]
            if recent_move else []
        ),
        "stockfish_short_search_not_deep_proof": engine,
        "game_result_hidden_to_avoid_hindsight": True,
    }


def coach_response(api_key: str, context: dict, messages: list[dict], task: str,
                   user_text: str = "", model: str = "gpt-4.1-mini") -> str:
    client = OpenAI(api_key=api_key, timeout=65.0, max_retries=1)
    # The evidence is passed afresh. Only prior dialogue, not stale board context, is kept.
    prior = [{"role": m["role"], "content": m["content"][:2200]}
             for m in messages[-14:] if m.get("role") in {"user", "assistant"}]
    task_text = {
        "START": "Start a genuine coaching conversation. Ask ONE concrete question tied to the next student move if supplied; otherwise ask what the student is trying to achieve here. Do not deliver the answers yet.",
        "CHAPTER": "Board has advanced to another real game moment. Briefly bridge from earlier discussion and ask ONE new position-specific question; do not rehash the opening introduction.",
        "REPLY": "Respond directly to the student's most recent message. Assess their reasoning, teach one useful principle grounded here, and ask one productive next question.",
        "PLAN": "The student requests a practical strategic plan. Explain a plausible objective for each side, the immediate priority, and what would change the plan. Keep it conversational. Do not invent forced lines.",
    }[task]
    prompt = ("CURRENT VERIFIED GAME CONTEXT (JSON):\n" + json.dumps(context, ensure_ascii=False, default=str)
              + "\n\nTASK: " + task_text + ("\nSTUDENT SAYS: " + user_text[:2000] if user_text else ""))
    response = client.responses.create(
        model=model, instructions=TUTOR_RULES,
        input=prior + [{"role": "user", "content": prompt}],
        max_output_tokens=420, store=False,
    )
    result = (response.output_text or "").strip()
    if not result:
        raise RuntimeError("The AI returned an empty answer. Please try again.")
    return result


def transcribe_recording(api_key: str, recording_bytes: bytes) -> str:
    if not recording_bytes:
        raise ValueError("No audio was recorded.")
    if len(recording_bytes) > 15_000_000:
        raise ValueError("Recording too large. Please record a shorter answer.")
    client = OpenAI(api_key=api_key, timeout=65.0, max_retries=1)
    result = client.audio.transcriptions.create(
        model="gpt-4o-mini-transcribe", file=("answer.wav", recording_bytes, "audio/wav"),
        prompt="Chess coaching discussion. Chess moves and squares may be mentioned, such as Nf3, d5 and f7.",
    )
    return result.text.strip()


def synthesize_speech(api_key: str, message: str) -> bytes:
    client = OpenAI(api_key=api_key, timeout=65.0, max_retries=1)
    # Spoken narration should not read Markdown or large engine data dumps.
    cleaned = re.sub(r"[`*_#]", "", message)[:1800]
    audio = client.audio.speech.create(model="gpt-4o-mini-tts", voice="sage", input=cleaned)
    return audio.content


def render_live_coach(*, raw_pgn: str, username: str, findings: list[dict],
                      engine_path: str, colors: dict, coordinates: bool,
                      highlight_last_move: bool, api_key: str, access_code: str,
                      model: str = "gpt-4.1-mini") -> None:
    st.subheader("♟️ Live chess lesson")
    st.caption("One game. An active conversation. The coach asks; you explain; the board moves with the lesson.")
    if not raw_pgn:
        st.info("Analyse a game first. Your most recent game will then be available to coach through.")
        return
    archive_signature = hashlib.sha256(raw_pgn.encode()).hexdigest()[:16]
    if st.session_state.get("live_archive_signature") != archive_signature:
        st.session_state.live_archive_signature = archive_signature
        st.session_state.live_archive_games = parse_games(raw_pgn, 250)
        st.session_state.live_coach_sessions = {}
    games = st.session_state.live_archive_games
    username_cf = username.casefold().strip()
    available = [(i, game) for i, game in enumerate(games, 1)
                 if username_cf in (game.headers.get("White", "").casefold(),
                                    game.headers.get("Black", "").casefold())]
    if not available:
        st.warning("No imported games match your username. Reanalyse with the correct account name.")
        return
    game_index = st.selectbox("Choose a game to discuss", [i for i, _ in available],
                              format_func=lambda i: next(
                                  f"Game {num}: {g.headers.get('White', '?')} vs {g.headers.get('Black', '?')}"
                                  for num, g in available if num == i), key="live_game_selection")
    game = next(g for i, g in available if i == game_index)
    student_white = game.headers.get("White", "").casefold() == username_cf
    positions, turns = replay(game)
    if not turns:
        st.info("This game has no replayable moves.")
        return
    found = [f for f in findings if f.get("game") == game_index]
    milestones = chapters(positions, turns, student_white, found)
    if not milestones:
        st.info("No teaching checkpoints were available in this game.")
        return
    session_id = game_key(raw_pgn, game_index)
    sessions = st.session_state.setdefault("live_coach_sessions", {})
    if session_id not in sessions:
        sessions[session_id] = {"ply": milestones[0]["ply"], "messages": [],
                                "engine_by_ply": {}, "audio": None, "audio_for": None, "pending_chapter": False}
    s = sessions[session_id]

    # Let the user move the actual game board without erasing conversation history.
    with st.container():
        nav1, nav2, nav3 = st.columns([1, 1, 2])
        if nav1.button("◀ Previous", disabled=s["ply"] == 0, key=f"live_back_{session_id}"):
            s["ply"] = max(0, s["ply"] - 1)
            s["pending_chapter"] = False
            s["audio"] = None
            st.rerun()
        if nav2.button("Next move ▶", disabled=s["ply"] >= len(turns), key=f"live_next_{session_id}"):
            s["ply"] = min(len(turns), s["ply"] + 1)
            s["pending_chapter"] = False
            s["audio"] = None
            st.rerun()
        chapter_options = list(range(len(milestones)))
        idx = nav3.selectbox("Teaching moments", chapter_options,
                             format_func=lambda k: milestones[k]["title"] +
                             f" (move {milestones[k]['ply']//2 + 1})", key=f"live_chapter_{session_id}")
        nxt1, nxt2 = st.columns(2)
        if nxt1.button("Go to teaching moment", key=f"live_jump_{session_id}", use_container_width=True):
            s["ply"] = milestones[idx]["ply"]
            s["pending_chapter"] = bool(s["messages"])
            s["audio"] = None
            st.rerun()
        if nxt2.button("Next teaching moment →", key=f"live_landmark_{session_id}", use_container_width=True):
            later = next((p["ply"] for p in milestones if p["ply"] > s["ply"]), None)
            if later is not None:
                s["ply"] = later
                s["pending_chapter"] = bool(s["messages"])
                s["audio"] = None
                st.rerun()
            else:
                st.info("You've reached the last planned teaching moment in this game.")

    ply = s["ply"]
    board = positions[ply]
    chapter = next((m["title"] for m in milestones if m["ply"] == ply),
                   "Move-by-move review")
    board_col, tutor_col = st.columns([1, 1.12], gap="large")
    with board_col:
        last_move = chess.Move.from_uci(turns[ply-1]["uci"]) if ply and highlight_last_move else None
        st.image(chess.svg.board(board=board, orientation=student_white,
                                 size=520, coordinates=coordinates, colors=colors,
                                 lastmove=last_move), use_container_width=True)
        st.caption(f"{chapter} · {phase(board)} · "
                   f"{('White' if board.turn else 'Black')} to move · "
                   f"Your side: {('White' if student_white else 'Black')}")
        if ply:
            recent = turns[max(0, ply - 6):ply]
            st.caption("Moves so far: " + " ".join(
                f"{t['number']}{'.' if t['color']=='White' else '...'}{t['san']}" for t in recent))
        if ply < len(turns) and board.turn == student_white:
            st.caption(f"Your historical next move: **{turns[ply]['san']}**. The coach can ask what you wanted to achieve.")
        if st.button("Reset conversation for this game", key=f"live_reset_{session_id}"):
            s["messages"] = []
            s["pending_chapter"] = False
            s["audio"] = None
            s["audio_for"] = None
            st.rerun()
    with tutor_col:
        if not api_key or not access_code:
            st.info("AI voice/chat requires OPENAI_API_KEY and AI_COACH_PASSCODE in Streamlit Secrets.")
            return
        if not st.session_state.get("ai_unlocked", False):
            with st.form("unlock_live_tutor"):
                supplied = st.text_input("Private AI tutor passcode", type="password")
                unlock = st.form_submit_button("Unlock live tutor")
            if unlock:
                import hmac
                if hmac.compare_digest(supplied, access_code):
                    st.session_state.ai_unlocked = True
                    st.rerun()
                else:
                    st.error("Incorrect passcode.")
            return

        def get_evidence() -> dict | None:
            if ply not in s["engine_by_ply"]:
                try:
                    s["engine_by_ply"][ply] = engine_checkpoint(board.fen(), engine_path, seconds=0.8)
                except Exception as exc:
                    s["engine_by_ply"][ply] = {"candidates": [],
                        "note": "Engine checkpoint unavailable: " + str(exc)}
            return s["engine_by_ply"][ply]

        def respond(task: str, message: str = "") -> None:
            with st.spinner("Coach is thinking about your position…"):
                evidence = get_evidence()
                context = make_context(game, positions, turns, ply, student_white, evidence, chapter)
                answer = coach_response(api_key, context, s["messages"], task,
                                        user_text=message, model=model)
            if message:
                s["messages"].append({"role": "user", "content": message, "ply": ply})
            s["messages"].append({"role": "assistant", "content": answer, "ply": ply})
            s["audio"] = None
            s["audio_for"] = None
            st.rerun()

        # A newly selected game moment automatically becomes the topic of
        # a single follow-up question. No separate 'generate a lesson' click.
        if s.get("pending_chapter") and s["messages"]:
            s["pending_chapter"] = False
            try:
                respond("CHAPTER")
            except Exception as exc:
                s["pending_chapter"] = False
                st.warning(f"The board moved, but the coach couldn't generate a follow-up: {exc}")
        s["pending_chapter"] = False

        if not s["messages"]:
            st.markdown("**Your coach will lead.** No written assessment forms, no wall of board facts.")
            if st.button("▶ Start my chess lesson", type="primary", use_container_width=True,
                         key=f"live_start_{session_id}"):
                try:
                    respond("START")
                except Exception as exc:
                    st.error(f"Couldn't start the lesson: {exc}")
            st.caption("We'll discuss your actual move intentions, the position's demands, and both players' plans.")
            return

        with st.container(height=390, border=True):
            for msg in s["messages"][-16:]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    if msg.get("ply") != ply:
                        st.caption(f"Discussed at move {msg['ply']//2+1}")
        quick1, quick2 = st.columns(2)
        if quick1.button("Ask me about this position", key=f"live_ask_{session_id}", use_container_width=True):
            try:
                respond("CHAPTER")
            except Exception as exc:
                st.error(f"Coach couldn't continue: {exc}")
        if quick2.button("Help me find a plan", key=f"live_plan_{session_id}", use_container_width=True):
            try:
                respond("PLAN")
            except Exception as exc:
                st.error(f"Coach couldn't explain the plan: {exc}")

        question = st.chat_input("Reply to your coach or ask anything…", key=f"live_message_{session_id}")
        if question and question.strip():
            try:
                respond("REPLY", question.strip())
            except Exception as exc:
                st.error(f"AI coach couldn't reply: {exc}")

        with st.form(f"voice_reply_{session_id}", clear_on_submit=True):
            clip = st.audio_input("🎙️ Speak your answer instead of typing")
            voice_submit = st.form_submit_button("Send voice message", use_container_width=True)
        if voice_submit:
            if clip is None:
                st.warning("Record something before sending.")
            else:
                try:
                    with st.spinner("Transcribing your explanation…"):
                        spoken = transcribe_recording(api_key, clip.getvalue())
                    if spoken:
                        respond("REPLY", spoken)
                    else:
                        st.info("I couldn't hear any words. Try speaking again.")
                except Exception as exc:
                    st.error(f"Voice message couldn't be sent: {exc}")

        last_answer = next((m["content"] for m in reversed(s["messages"])
                            if m["role"] == "assistant"), None)
        if last_answer:
            st.caption("You can also hear the tutor's latest reply (AI-generated voice; extra API usage).")
            if st.button("🔊 Play coach's answer", key=f"live_voice_out_{session_id}"):
                try:
                    answer_hash = hashlib.sha256(last_answer.encode()).hexdigest()
                    if s.get("audio_for") != answer_hash:
                        with st.spinner("Generating spoken reply…"):
                            s["audio"] = synthesize_speech(api_key, last_answer)
                            s["audio_for"] = answer_hash
                except Exception as exc:
                    st.error(f"Couldn't generate speech: {exc}")
            if s.get("audio") and s.get("audio_for") == hashlib.sha256(last_answer.encode()).hexdigest():
                st.audio(s["audio"], format="audio/mp3")
    st.caption("The tutor uses brief Stockfish checkpoints and board facts, not exhaustive perfect-game analysis. "
               "Mic input is push-to-talk, not a continuous live call. Conversations are stored in this browser session, not a database.")
