"""Streamlit frontend for Chess Pattern Coach."""
from __future__ import annotations

import os
import shutil
import hashlib
import json
import hmac

import chess
import chess.svg
import pandas as pd
import streamlit as st

from analysis import fetch_chesscom, fetch_lichess, parse_games, scan_games
from coach import position_evidence, prompts_for_stage, reflection_comparison
from concept_coach import candidate_review, stage_questions, ai_explain


def setting_from_secrets(name: str) -> str:
    # Cloud secrets are mapped into environment variables on Streamlit Cloud.
    value = os.environ.get(name, "")
    if value:
        return value
    try:
        return str(st.secrets.get(name, ""))
    except (FileNotFoundError, KeyError):
        return ""


st.set_page_config(page_title="Chess Intelligence Coach", page_icon="♞", layout="wide")
st.markdown("""
<style>
  .block-container {max-width: 1180px; padding-top: 2rem}
  h1 {letter-spacing: -.035em}
  div[data-testid="stMetric"] {border:1px solid #38404b; border-radius:12px; padding:16px}
  .eyebrow {font-size:.78rem; font-weight:700; color:#a0adbd; letter-spacing:.17em}
  .muted {color:#a0adbd}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="eyebrow">YOUR GAMES. YOUR BLIND SPOTS.</div>', unsafe_allow_html=True)
st.title("♞ Chess Intelligence Coach")
st.caption("Your games → critical decisions → understanding both sides' plans → personalised lessons.")

with st.sidebar:
    st.header("Import your games")
    provider = st.selectbox("Source", ["Chess.com", "Lichess", "PGN upload"])
    username = st.text_input("Your chess username", value="dav4life", help="Used to identify your moves in each game")
    if provider == "Chess.com":
        st.caption("Imports your most recent completed **rapid** games, including wins and losses. No password needed.")
    uploaded = st.file_uploader("Upload a .pgn file", type=["pgn", "txt"]) if provider == "PGN upload" else None
    limit = st.slider("Recent games to scan", 10, 250, 30, step=10)
    think_time = st.select_slider("Engine seconds / position", options=[0.05, 0.08, 0.15, 0.3, 0.5], value=0.08)
    threshold = st.slider("Minimum centipawn loss", 70, 350, 135, 5)
    # Debian installs the Stockfish apt package at /usr/games/stockfish,
    # which is not always on the PATH in Streamlit Community Cloud.
    known_engine_paths = [
        os.environ.get("STOCKFISH_PATH"),
        shutil.which("stockfish"),
        "/usr/games/stockfish",
        "/usr/bin/stockfish",
        "/opt/homebrew/bin/stockfish",  # macOS Apple Silicon
        "/usr/local/bin/stockfish",     # macOS Intel/Homebrew
    ]
    detected_engine = next(
        (p for p in known_engine_paths if p and os.path.isfile(p) and os.access(p, os.X_OK)),
        "stockfish",
    )
    engine_path = st.text_input("Stockfish executable", value=detected_engine)
    st.caption("Try 10 games first, then 30. The engine evaluates many positions per game; larger imports can take several minutes.")
    go = st.button("Analyse my games", type="primary", use_container_width=True)

if go:
    if not username.strip():
        st.error("Enter the username shown in your game headers.")
    elif uploaded is None and provider == "PGN upload":
        st.error("Upload at least one PGN file.")
    else:
        try:
            with st.spinner("Retrieving public game history…"):
                if provider == "Chess.com":
                    pgn = fetch_chesscom(username.strip(), limit)
                elif provider == "Lichess":
                    pgn = fetch_lichess(username.strip(), limit)
                else:
                    pgn = uploaded.getvalue().decode("utf-8-sig", errors="replace")
                games = parse_games(pgn, limit)
            if not games:
                st.error("No readable standard-chess games found. Check the username or PGN file.")
            else:
                bar = st.progress(0.0, text="Starting analysis…")
                def progress(done: int, total: int):
                    bar.progress(done / max(total, 1), text=f"Analysed {done}/{total} games")
                with st.spinner("Stockfish is evaluating your positions…"):
                    report = scan_games(games, username.strip(), engine_path, think_time, threshold, progress)
                st.session_state.report = report
                st.session_state.report_username = username.strip()
                bar.empty()
        except Exception as exc:
            st.error(f"Analysis could not finish: {exc}")
            st.info("Ensure Stockfish is installed and the executable path is correct. For Chess.com/Lichess, check that the username has public archived games.")

report = st.session_state.get("report")
if report is None:
    st.markdown("### What it does")
    a, b, c = st.columns(3)
    a.markdown("**1. Read your games**\n\nFetch Chess.com or Lichess history, or upload PGN.")
    b.markdown("**2. Discover repeated errors**\n\nFind engine-confirmed mistakes and likely forks, pins, skewers, mating ideas and loose pieces.")
    c.markdown("**3. Train your blind spots**\n\nReview the exact positions where you missed a better move.")
    st.info("This version runs real analysis after you supply your own username or PGN. It does not generate fictitious ratings or weakness statistics.")
    st.stop()

findings = report["findings"]
st.markdown(f"#### Analysis for **{st.session_state.get('report_username', '')}**")
a, b, c, d = st.columns(4)
a.metric("Games examined", report["games"])
b.metric("Your moves examined", report["positions"])
c.metric("Meaningful evaluation losses", len(findings))
d.metric("Motif-tagged errors", sum(f["theme"] != "Other evaluation losses" for f in findings))

if not findings:
    st.success("No position exceeded your chosen loss threshold. Try a lower threshold or more games.")
    st.stop()

df = pd.DataFrame(findings)
summary, concept_review, training, all_positions = st.tabs(["Weakness profile", "Understand a position", "Tactic practice", "All findings"])

with summary:
    st.subheader("Most frequent error categories")
    st.caption("These counts are engine-confirmed evaluation losses classified by simple motif rules. Uncertain cases are shown as 'Other evaluation losses'.")
    counts = df.groupby("theme").size().sort_values(ascending=False)
    st.bar_chart(counts.rename("Errors"), horizontal=True)
    st.markdown("##### Tactical opportunities recognised by the first-pass detector")
    st.caption("An opportunity here means Stockfish's best move had a detectable geometric motif. It's an estimate, not a definitive measure of every possible tactic.")
    opportunities = report.get("motif_events", {})
    missed = report.get("motif_missed", {})
    if opportunities:
        rows = []
        for name, count in sorted(opportunities.items(), key=lambda p: -p[1]):
            rows.append({"Motif": name, "Detected opportunities": count,
                         "Missed with a significant eval loss": missed.get(name, 0),
                         "Missed %": round(100 * missed.get(name, 0) / count) if count else 0})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.caption("No geometric tactical opportunities were detected at this analysis setting.")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### Errors by game phase")
        st.bar_chart(df.groupby("stage").size().rename("Errors"))
    with col2:
        st.markdown("##### Mistake severity")
        st.bar_chart(df.groupby("severity").size().rename("Errors"))
    top = counts.index[0]
    st.info(f"**Your most frequent detected category:** {top} ({counts.iloc[0]} occurrences). Start with those training positions.")

with concept_review:
    st.subheader("Think before you reveal")
    st.caption("This guided review does not pretend to know your thinking from your moves. It records your actual reasoning first, then shows engine-grounded evidence.")
    # Choose diverse errors, balancing stages and games rather than showing
    # five nearly identical tactical blunders from a single match.
    ordered = sorted(findings, key=lambda r: r["loss_cp"], reverse=True)
    sampled = []
    chosen_games = set()
    for stage in ("Opening", "Middlegame", "Endgame"):
        choices = [f for f in ordered if f["stage"] == stage and f["game"] not in chosen_games]
        if choices and len(sampled) < 5:
            candidate = choices[0]
            sampled.append(candidate)
            chosen_games.add(candidate["game"])
    for candidate in ordered:
        if len(sampled) >= 5:
            break
        if candidate in sampled or candidate["game"] in chosen_games:
            continue
        sampled.append(candidate)
        chosen_games.add(candidate["game"])
    if len(sampled) < 5:
        for candidate in ordered:
            if len(sampled) >= 5:
                break
            if candidate not in sampled:
                sampled.append(candidate)
    selected_index = st.selectbox(
        "Pick an instructive position",
        list(range(len(sampled))),
        format_func=lambda i: f"Game {sampled[i]['game']} · {sampled[i]['stage']} · move {sampled[i]['move_number']} · {sampled[i]['color']} to move",
    )
    position = sampled[selected_index]
    b = chess.Board(position["fen"])
    pid = hashlib.sha256((position["fen"] + str(position["game"]) + position["played_uci"]).encode()).hexdigest()[:14]
    if "coach_attempts" not in st.session_state:
        st.session_state.coach_attempts = {}
    attempt = st.session_state.coach_attempts.get(pid)

    board_col, coach_col = st.columns([1, 1.1], gap="large")
    with board_col:
        st.image(chess.svg.board(
            board=b,
            orientation=chess.WHITE if position["color"] == "White" else chess.BLACK,
            size=490, coordinates=True,
        ), use_container_width=True)
        st.caption(f"Position from game {position['game']} · {position['stage']}. Engine answer hidden until your reflection is submitted.")
        with st.expander("Your position-reading checklist", expanded=True):
            for question in prompts_for_stage(position["stage"]):
                st.markdown("• " + question)
    with coach_col:
        if attempt is None:
            st.markdown("#### Your turn to think")
            st.markdown("Before trying a move, decide which features of the position actually matter.")
            with st.form(f"coach_form_{pid}"):
                priority = st.selectbox("1. What's the main priority here?", [
                    "Immediate checks, captures or threats", "King safety",
                    "Piece development / activity", "Pawn structure / weak squares",
                    "Endgame technique", "I genuinely don't know",
                ])
                counterplay = st.text_area("2. What might your opponent be threatening?", height=80,
                                           placeholder="Name a specific piece, square, pawn break or forcing move.")
                plan = st.text_area("3. What is your plan, and why?", height=90,
                                    placeholder="I want to... because...; my opponent wants to...")
                my_move = st.text_input("4. Your chosen move (SAN or UCI)", placeholder="e.g. Nf3, Qh5+, e2e4")
                submitted = st.form_submit_button("Commit my thinking", type="primary", use_container_width=True)
            if submitted:
                if not plan.strip() or not my_move.strip():
                    st.warning("Write a plan and a move before submitting. 'I don't know' is a valid plan.")
                else:
                    try:
                        chosen = b.parse_san(my_move.strip())
                    except (ValueError, AssertionError):
                        try:
                            chosen = chess.Move.from_uci(my_move.strip())
                        except ValueError:
                            chosen = None
                    if chosen is None or chosen not in b.legal_moves:
                        st.error("Please enter a legal move in SAN or UCI format.")
                    else:
                        st.session_state.coach_attempts[pid] = {
                            "fen": position["fen"], "game": position["game"],
                            "stage": position["stage"], "priority": priority,
                            "opponent_threat": counterplay.strip(), "plan": plan.strip(),
                            "chosen_move": b.san(chosen), "chosen_uci": chosen.uci(),
                            "engine_best_uci": position["best_uci"],
                        }
                        st.rerun()
        else:
            st.success("Your assessment has been recorded. Let's understand the position.")
            st.markdown("#### Your original thinking")
            st.write(f"**Priority:** {attempt['priority']}")
            st.write(f"**Your plan:** {attempt['plan']}")
            st.write(f"**Opponent's possible threat:** {attempt.get('opponent_threat') or 'Not specified'}")
            st.write(f"**Your candidate move:** {attempt['chosen_move']}")
            if "deep_reviews" not in st.session_state:
                st.session_state.deep_reviews = {}
            if "ai_lessons" not in st.session_state:
                st.session_state.ai_lessons = {}
            if "ai_chats" not in st.session_state:
                st.session_state.ai_chats = {}
            if "ai_errors" not in st.session_state:
                st.session_state.ai_errors = {}

            if pid not in st.session_state.deep_reviews:
                st.info("Your earlier review used fast screening analysis. The next step searches this particular position more deeply, checks several candidate moves, and extracts learning cues for both sides.")
                if st.button("Build my positional lesson", type="primary", key=f"deepen_{pid}", use_container_width=True):
                    try:
                        with st.spinner("Examining candidate plans with Stockfish…"):
                            st.session_state.deep_reviews[pid] = candidate_review(
                                position["fen"], attempt["chosen_uci"], position["played_uci"],
                                engine_path, seconds=1.0,
                            )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not complete deeper analysis: {exc}")
            else:
                deep = st.session_state.deep_reviews[pid]
                st.markdown("### Read the position, not just the engine")
                st.caption("Verified board features below are evidence to reason from. Their strategic implications depend on the exact variations.")
                facts = deep["facts"]
                key_topics = lambda f: (0 if "Immediate" in f["topic"] else
                                        1 if "targets" in f["topic"] else
                                        2 if "pawn structure" in f["topic"] else
                                        3 if "development" in f["topic"] else
                                        4 if "Open files" in f["topic"] else 5)
                for fact in sorted(facts, key=key_topics)[:5]:
                    st.markdown(f"**{fact['topic']}** — {fact['fact']}")
                    st.caption(f"Why it matters: {fact['why']}")
                with st.expander("All verified board features (both sides)"):
                    for fact in facts:
                        st.markdown(f"**{fact['topic']}** — {fact['fact']}")
                        st.caption(f"Why: {fact['why']} · Ask: {fact['question']}")

                st.markdown("#### How to approach this type of position")
                for n, question in enumerate(stage_questions(position["stage"], facts), 1):
                    st.markdown(f"{n}. {question}")

                st.markdown("#### Compare your candidate plans")
                chosen = deep["comparisons"]["chosen"]
                original = deep["comparisons"]["original"]
                st.write(f"**Your proposed move {chosen['move']}:** evaluation {chosen['evaluation']} from your perspective; potential reply {chosen['opponent_reply']}.")
                st.write(f"**Your move in the game {original['move']}:** evaluation {original['evaluation']}; potential reply {original['opponent_reply']}.")
                st.caption("These estimates come from a deeper but still limited engine search. A score alone does not explain the positional idea.")

                with st.expander("Stockfish's candidate moves and concrete variations", expanded=False):
                    for alternative in deep["candidates"]:
                        st.markdown(f"**{alternative['rank']}. {alternative['move']}** ({alternative['evaluation']})")
                        st.caption(alternative["continuation"])
                    st.write("After your proposed move: " + chosen["continuation"])
                    st.write("After your original move: " + original["continuation"])
                    st.caption("Tactical motif detector: " + position["theme"] + ". " + position["explanation"])

                api_key = setting_from_secrets("OPENAI_API_KEY")
                access_code = setting_from_secrets("AI_COACH_PASSCODE")
                st.markdown("### Your conversational chess coach")
                if not api_key:
                    st.info("To unlock explanations of the plans and an interactive coaching conversation, add an OpenAI API key to your **Streamlit app's Secrets**. Until then, the board evidence, questions and candidate comparisons still work without AI or charges.")
                    st.caption("Secret format: OPENAI_API_KEY = \"sk-...\". Never paste the key into GitHub or into this chat.")
                elif not access_code:
                    st.warning("This is a publicly accessible app. To prevent strangers using your paid API credits, also add AI_COACH_PASSCODE to your Streamlit Secrets. The AI coach stays disabled until you do.")
                else:
                    if not st.session_state.get("ai_unlocked", False):
                        with st.form("ai_access_form"):
                            code = st.text_input("Private AI coach access code", type="password")
                            if st.form_submit_button("Unlock AI coach"):
                                if hmac.compare_digest(code, access_code):
                                    st.session_state.ai_unlocked = True
                                    st.rerun()
                                else:
                                    st.error("Incorrect access code.")
                    if st.session_state.get("ai_unlocked", False):
                        context = {"position": {k: position.get(k) for k in
                                   ("fen", "stage", "color", "game", "move_number", "theme", "loss_cp")},
                                   "student_reflection": attempt, "verified_engine_and_board_evidence": deep}
                        model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
                        if pid not in st.session_state.ai_lessons:
                            if st.button("Teach me the plans and principles", key=f"teach_{pid}", type="primary", use_container_width=True):
                                try:
                                    with st.spinner("Building a personalised lesson grounded in the position…"):
                                        st.session_state.ai_lessons[pid] = ai_explain(context, api_key, model=model)
                                    st.session_state.ai_errors.pop(pid, None)
                                    st.rerun()
                                except Exception as exc:
                                    st.session_state.ai_errors[pid] = str(exc)
                        if pid in st.session_state.ai_errors:
                            st.error("AI request failed: " + st.session_state.ai_errors[pid])
                        if pid in st.session_state.ai_lessons:
                            st.markdown(st.session_state.ai_lessons[pid])
                            st.divider()
                            st.markdown("#### Ask why — and challenge the coach")
                            chat = st.session_state.ai_chats.setdefault(pid, [])
                            for turn in chat:
                                with st.chat_message(turn["role"]):
                                    st.markdown(turn["content"])
                            with st.form(f"chat_form_{pid}", clear_on_submit=True):
                                question = st.text_input("Your follow-up", placeholder="Why is that square weak? What if I exchange queens?")
                                ask = st.form_submit_button("Ask my coach")
                            if ask and question.strip():
                                try:
                                    with st.spinner("Checking the engine evidence and teaching the concept…"):
                                        answer = ai_explain(context, api_key, question=question.strip(), history=chat, model=model)
                                    chat.extend([{"role": "user", "content": question.strip()},
                                                 {"role": "assistant", "content": answer}])
                                    st.rerun()
                                except Exception as exc:
                                    st.error("Follow-up failed: " + str(exc))
                        st.caption("AI-generated interpretations can be wrong. Check critical claims against the engine variations; no account data or keys are needed for the Stockfish analysis itself.")

            if st.button("Try this position again", key=f"retry_{pid}"):
                st.session_state.coach_attempts.pop(pid, None)
                st.session_state.deep_reviews.pop(pid, None)
                st.session_state.ai_lessons.pop(pid, None)
                st.session_state.ai_chats.pop(pid, None)
                st.session_state.ai_errors.pop(pid, None)
                st.rerun()
    if st.session_state.coach_attempts:
        st.download_button("Export my reasoning as JSON",
            json.dumps(list(st.session_state.coach_attempts.values()), indent=2),
            file_name="chess_coach_my_reasoning.json", mime="application/json")

with training:
    st.subheader("Replay the position, not just the move")
    themes = ["All themes"] + sorted(df["theme"].unique().tolist())
    theme_filter = st.selectbox("Practice category", themes)
    filtered = [r for r in findings if theme_filter == "All themes" or r["theme"] == theme_filter]
    pos = st.number_input("Exercise", min_value=1, max_value=len(filtered), value=1)
    selected = filtered[pos - 1]
    board = chess.Board(selected["fen"])
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        drawing = chess.svg.board(board=board, orientation=chess.WHITE if selected["color"] == "White" else chess.BLACK,
                                  size=460, coordinates=True)
        st.image(drawing, use_container_width=True)
    with right:
        st.markdown(f"**Game {selected['game']} · {selected['color']} to play · move {selected['move_number']}**")
        st.markdown(f"**Category:** {selected['theme']}")
        st.markdown(f"**Stage:** {selected['stage']} · **Engine loss:** {selected['loss_cp']} cp")
        st.markdown("Find the strongest move before revealing the answer.")
        attempt = st.text_input("Your move (SAN or UCI)", key=f"attempt_{selected['game']}_{selected['move_number']}_{selected['fen']}", placeholder="e.g. Nf7+ or g5f7")
        if attempt:
            try:
                m = board.parse_san(attempt.strip())
                if m.uci() == selected["best_uci"]:
                    st.success("You found Stockfish's top move.")
                else:
                    st.warning("That isn't the engine's top move here. It may still be playable; this MVP checks only the first engine choice.")
            except ValueError:
                try:
                    m = chess.Move.from_uci(attempt.strip())
                    if m in board.legal_moves and m.uci() == selected["best_uci"]:
                        st.success("You found Stockfish's top move.")
                    else:
                        st.warning("Try another legal move, or reveal the line.")
                except ValueError:
                    st.warning("Enter a legal move in notation such as Nf7+ or g5f7.")
        reveal = st.checkbox("Reveal Stockfish's solution", key=f"reveal_{selected['game']}_{selected['move_number']}_{selected['fen']}")
        if reveal:
            st.markdown(f"**You played:** {selected['played']}")
            st.markdown(f"**Better move:** {selected['best']}")
            st.markdown(f"**Engine continuation:** {selected['principal_variation']}")
            st.markdown(selected["explanation"])
            url = selected.get("game_url", "")
            if url.startswith("https://"):
                st.link_button("Open original game", url)
    st.caption("Note: Engine evaluation and pattern labels are approximations. Increase analysis time to verify borderline positions.")

with all_positions:
    st.subheader("All analysed mistakes")
    shown = df[["game", "date", "color", "move_number", "stage", "played", "best", "loss_cp", "theme", "severity"]].copy()
    st.dataframe(shown, hide_index=True, use_container_width=True)
    st.download_button("Download findings as CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name="my_chess_patterns.csv", mime="text/csv")
