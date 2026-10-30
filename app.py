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
from game_coach import (replay, chapters, board_lenses, change_after_move,
                        FOUNDATIONS, engine_checkpoint, ai_game_lesson, teaching_context,
                        chapter_engine_evidence, ai_full_game_story)
from analysis import phase, motifs_for_move
from diagnosis import investigate


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

# Palette colours applied to every chess.svg.board() diagram.
# Changing this setting only changes appearance — not game state or engine analysis.
BOARD_THEMES = {
    "Classic Wood": {
        "square light": "#f0d9b5", "square dark": "#b58863",
        "square light lastmove": "#f2df83", "square dark lastmove": "#c6a05b",
        "margin": "#e8decf", "coord": "#47392b",
    },
    "Chess.com Green": {
        "square light": "#eeeed2", "square dark": "#769656",
        "square light lastmove": "#f5f58c", "square dark lastmove": "#baca44",
        "margin": "#e2e4d0", "coord": "#3c5630",
    },
    "Lichess Green": {
        "square light": "#ffffdd", "square dark": "#86a666",
        "square light lastmove": "#f2ef88", "square dark lastmove": "#c3cf66",
        "margin": "#eef0dc", "coord": "#405b30",
    },
    "Slate Blue": {
        "square light": "#dee3e6", "square dark": "#819aac",
        "square light lastmove": "#f2e58f", "square dark lastmove": "#a2bba1",
        "margin": "#d8e0e7", "coord": "#283b49",
    },
    "Midnight": {
        "square light": "#afbacc", "square dark": "#47576b",
        "square light lastmove": "#e2cb81", "square dark lastmove": "#8f9566",
        "margin": "#283443", "coord": "#f1f4f8",
    },
}

st.markdown('<div class="eyebrow">YOUR GAMES. YOUR BLIND SPOTS.</div>', unsafe_allow_html=True)
st.title("♞ Chess Intelligence Coach")
st.caption("Your games → critical decisions → understanding both sides' plans → personalised lessons.")

with st.sidebar:
    st.header("Board appearance")
    board_theme = st.selectbox("Chessboard theme", list(BOARD_THEMES), index=0,
                               help="Applies to whole-game replay, position reviews and tactic practice.")
    show_board_coordinates = st.checkbox("Show coordinates", value=True)
    highlight_last_move = st.checkbox("Highlight last move in replay", value=True)
    board_colors = BOARD_THEMES[board_theme]
    st.divider()
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
                st.session_state.games_pgn = pgn
                st.session_state.pop("diagnosis_update_notice", None)
                for cache_key in ("game_coach_reflections", "game_coach_engine",
                                  "game_coach_lessons", "game_coach_chats", "game_coach_stories"):
                    st.session_state.pop(cache_key, None)
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
    b.markdown("**2. Discover repeated errors**\n\nScreen costly moves with Stockfish, then test tactical motifs and positional hypotheses.")
    c.markdown("**3. Train your blind spots**\n\nReview the exact positions where you missed a better move.")
    st.info("This version runs real analysis after you supply your own username or PGN. It does not generate fictitious ratings or weakness statistics.")
    st.stop()

all_findings = report["findings"]
# A deeper search can overturn a short first-pass evaluation. Do not present
# such positions as mistakes, practice exercises or strategic weaknesses.
findings = [f for f in all_findings if f.get("confidence") != "Revised"]
revised_count = len(all_findings) - len(findings)
st.markdown(f"#### Analysis for **{st.session_state.get('report_username', '')}**")
a, b, c, d = st.columns(4)
a.metric("Games examined", report["games"])
b.metric("Your moves examined", report["positions"])
c.metric("Screened mistakes", len(findings))
d.metric("Unresolved cases", sum(f.get("confidence") == "Unresolved" for f in findings))

if not findings:
    st.success("No significant mistakes are currently confirmed in this sample. Try more games or a longer engine check.")
    if revised_count:
        st.caption(f"{revised_count} fast-pass mistake(s) were overturned by deeper analysis.")
    st.stop()

df = pd.DataFrame(findings)
summary, game_walkthrough, concept_review, training, all_positions = st.tabs(["Weakness profile", "Whole-game coach", "Understand a position", "Tactic practice", "All findings"])

with summary:
    st.subheader("What your evaluation losses may be teaching you")
    st.caption("Fast Stockfish analysis screens costly decisions; this is not a definitive list of mistakes. Labels distinguish direct evidence from possible strategic clues. A motif's geometry does NOT prove why the move was bad.")
    diagnostic_counts = df["confidence"].value_counts()
    cols = st.columns(3)
    cols[0].metric("Supported consequences", int(diagnostic_counts.get("Supported", 0)))
    cols[1].metric("Strategic / tactical hypotheses", int(diagnostic_counts.get("Candidate", 0)))
    cols[2].metric("Needs deeper investigation", int(diagnostic_counts.get("Unresolved", 0)))
    if revised_count:
        st.info(f"{revised_count} first-pass mistake(s) were **not confirmed by deeper engine analysis** and have been removed from the weakness profile and practice queue.")

    explained = df[df["confidence"].isin(["Supported", "Candidate"])]
    if not explained.empty:
        counts = explained.groupby("theme").size().sort_values(ascending=False)
        st.markdown("##### Working learning themes")
        st.bar_chart(counts.rename("Occurrences"), horizontal=True)
        st.caption("Supported consequences and tentative hypotheses are combined here for exploration—not treated as proven, independent weaknesses.")
    else:
        counts = pd.Series(dtype=int)
        st.info("No explanations were supported by the first pass. Try deeper investigation below rather than assuming a specific chess weakness.")

    with st.expander("🔎 Investigate inconclusive decisions with deeper Stockfish analysis", expanded=bool(diagnostic_counts.get("Unresolved", 0))):
        st.markdown("**An unexplained engine drop isn't a diagnosis.** Reanalyse the actual position and its continuation at a slower engine setting, then inspect concrete evidence or retain an explicit unknown.")
        unresolved = sorted((i for i, f in enumerate(findings) if f.get("confidence") == "Unresolved"),
                            key=lambda ix: bool(findings[ix].get("rechecked")))
        if unresolved:
            st.write(f"{len(unresolved)} unresolved positions currently in this analysis.")
            chosen = st.selectbox(
                "Choose a position to investigate", unresolved,
                format_func=lambda ix: (f"Game {findings[ix]['game']}, move {findings[ix]['move_number']}, "
                                        f"{findings[ix]['color']}: {findings[ix]['played']} "
                                        f"({findings[ix]['loss_cp']} cp)"),
            )
            batch_n = st.select_slider("Positions to recheck", options=[1, 5, 10, 20], value=5,
                                       help="Each position gets a deeper search both before and after your move. Start with 5 to avoid long cloud computations.")
            seconds = st.select_slider("Seconds per side of the decision", options=[0.5, 1.0, 1.5, 2.0], value=1.5)
            c_single, c_batch = st.columns(2)
            recheck_one = c_single.button("Recheck selected position", use_container_width=True)
            recheck_batch = c_batch.button("Recheck unresolved batch", use_container_width=True)
            if recheck_one or recheck_batch:
                targets = [chosen] if recheck_one else unresolved[:batch_n]
                done = 0
                progress_bar = st.progress(0, text="Checking deeper engine lines…")
                for n, ix in enumerate(targets, 1):
                    try:
                        new_result = investigate(findings[ix], engine_path, seconds=seconds,
                                                 threshold_cp=report.get("threshold_cp", 135),
                                                 motif_detector=motifs_for_move, phase_detector=phase)
                        findings[ix].update(new_result)
                        findings[ix]["rechecked"] = True
                        done += 1
                    except Exception as exc:
                        st.warning(f"Game {findings[ix]['game']}, move {findings[ix]['move_number']}: {exc}")
                    progress_bar.progress(n/len(targets), text=f"Rechecked {n}/{len(targets)} positions")
                st.session_state.diagnosis_update_notice = f"Rechecked {done}/{len(targets)} positions with deeper engine search. Some may correctly remain unresolved."
                st.rerun()
        else:
            st.success("No unresolved cases remain in the current results. The candidate labels still require interpretation before being considered proven weaknesses.")

    if st.session_state.get("diagnosis_update_notice"):
        st.info(st.session_state.pop("diagnosis_update_notice"))

    with st.expander("Inspect the reason and evidence for any classified move"):
        selected_index = st.selectbox("Decision", list(range(len(findings))),
                                     format_func=lambda i: (f"Game {findings[i]['game']} · move {findings[i]['move_number']} "
                                                            f"· {findings[i]['theme']}"), key="inspect_classification")
        selected_finding = findings[selected_index]
        st.markdown(f"**{selected_finding['theme']}** · {selected_finding.get('confidence', 'Unrated')} evidence")
        st.write(selected_finding['explanation'])
        for signal in selected_finding.get("evidence", []):
            st.markdown("- " + signal)
        st.markdown("**Question to investigate:** " + selected_finding.get("question", "Compare the tactical variations."))
        st.caption("Engine best line: " + selected_finding.get("principal_variation", ""))
        st.caption("After your move: " + selected_finding.get("punishment_line", ""))

    st.markdown("##### Tactical opportunities recognised by the first-pass detector")
    st.caption("Detected geometries in the fast engine's chosen moves, not confirmed tactical wins; the percentages are screening indicators only.")
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
    if not counts.empty:
        top = counts.index[0]
        st.info(f"**Most common learning hypothesis:** {top} ({counts.iloc[0]} occurrences). Review the evidence before treating it as a confirmed weakness.")

with game_walkthrough:
    st.subheader("Learn the entire game — not just isolated mistakes")
    st.caption("Move through the game, stop at turning points, and learn what each phase is trying to achieve. The AI tutor uses the full move sequence and board facts; Stockfish checks the selected moment, not every move at once.")
    with st.expander("Start here: what are you actually trying to achieve in chess?", expanded=True):
        st.markdown("""**The goal is to create advantages that eventually allow you to attack the king, win material, or promote a pawn.** You do that by giving your pieces useful jobs, controlling important squares, creating targets, and preventing your opponent's plan.

**The five questions before most moves:**

1. **Safety:** What did the last move threaten? Are there checks, captures or undefended pieces?
2. **Space and squares:** Which central or forward squares would make my pieces stronger? What protects them?
3. **Pieces:** Which of my pieces has the least useful job? Where could it improve?
4. **Pawns:** Which pawn moves could open a route or create a weakness, for either side?
5. **Plan:** What is my 2–3 move objective, and what can the opponent do to stop it?

**Strong square:** a square that gives a piece influence and can be held safely. **Weak square:** a square that is hard to defend or challenge, especially with pawns. **Outpost:** typically an advanced square where a knight is supported and difficult for enemy pawns to dislodge. They are *potential targets*, not automatic commands to move there.

A useful plan might simply be: **improve my worst knight → contest an open file with a rook → attack a weak pawn**. It doesn't have to be a direct king attack.""")
    raw_games = st.session_state.get("games_pgn", "")
    if not raw_games:
        st.info("Please run 'Analyse my games' once after this update. The game archive is stored in this session for the guided replay.")
    else:
        replay_games = parse_games(raw_games, 250)
        player = st.session_state.get("report_username", username).casefold()
        matching = [(i, game) for i, game in enumerate(replay_games, 1)
                    if player in (game.headers.get("White", "").casefold(), game.headers.get("Black", "").casefold())]
        if not matching:
            st.info("No games matching your username were found in the current session. Please reanalyse.")
        else:
            game_numbers = [i for i, _ in matching]
            by_number = dict(matching)
            game_number = st.selectbox(
                "Choose a game", game_numbers,
                format_func=lambda i: (f"Game {i} · {by_number[i].headers.get('White', '?')} vs "
                                       f"{by_number[i].headers.get('Black', '?')} · "
                                       f"{by_number[i].headers.get('Result', '*')} · "
                                       f"{by_number[i].headers.get('Date', '')}"),
                key="full_game_choice",
            )
            game = by_number[game_number]
            player_color = game.headers.get("White", "").casefold() == player
            positions, turns = replay(game)
            game_findings = [f for f in findings if f["game"] == game_number]
            landmarks = chapters(positions, turns, player_color, game_findings)
            replay_key = f"fullgame_ply_{game_number}"
            if replay_key not in st.session_state:
                st.session_state[replay_key] = 0 if player_color else min(1, len(turns))
            def jump_to(k, index):
                st.session_state[k] = index

            if turns:
                top_left, top_right = st.columns([2, 1], gap="medium")
                with top_left:
                    landmark_index = st.selectbox(
                        "Jump to a strategic chapter", range(len(landmarks)),
                        format_func=lambda i: f"{landmarks[i]['title']} · move {(landmarks[i]['ply']//2)+1}",
                        key=f"landmark_choice_{game_number}",
                    )
                with top_right:
                    st.write(" ")
                    st.button("Go to chapter", on_click=jump_to,
                              args=(replay_key, landmarks[landmark_index]["ply"]),
                              use_container_width=True)
                p1, p2, p3 = st.columns([1, 1, 3])
                with p1:
                    st.button("◀ Previous", key=f"prev_move_{game_number}",
                              on_click=jump_to,
                              args=(replay_key, max(0, st.session_state[replay_key]-1)),
                              disabled=st.session_state[replay_key] == 0, use_container_width=True)
                with p2:
                    st.button("Next ▶", key=f"next_move_{game_number}",
                              on_click=jump_to,
                              args=(replay_key, min(len(turns), st.session_state[replay_key]+1)),
                              disabled=st.session_state[replay_key] == len(turns), use_container_width=True)
                with p3:
                    st.slider("Walk through every half-move", 0, len(turns), key=replay_key,
                              help="0 is the starting position, 1 is after White's first move, 2 after Black's first move, etc.")

                ply = st.session_state[replay_key]
                board = positions[ply]
                selected_phase = phase(board)
                chapter = next((c for c in landmarks if c["ply"] == ply), None)
                if chapter:
                    st.info(f"**Chapter: {chapter['title']}** — This is a useful moment to reassess your plan.")
                player_turn = board.turn == player_color
                left, right = st.columns([1, 1.1], gap="large")
                with left:
                    replay_lastmove = (chess.Move.from_uci(turns[ply - 1]["uci"])
                                       if ply > 0 and highlight_last_move else None)
                    st.image(chess.svg.board(board=board, orientation=player_color,
                        size=520, coordinates=show_board_coordinates,
                        colors=board_colors, lastmove=replay_lastmove),
                        use_container_width=True)
                    st.caption(f"After {ply} half-moves · {selected_phase} (approximate) · "
                               f"{'Your' if player_turn else 'Opponent’s'} turn" +
                               (" · Game move sequence finished" if ply == len(turns) else ""))
                    previous = turns[max(0, ply-8):ply]
                    if previous:
                        st.markdown("**How we arrived here:** " + "  ".join(
                            f"{t['number']}{'.' if t['color']=='White' else '...'}{t['san']}" for t in previous))
                    if ply > 0:
                        with st.expander("What changed on the last move?", expanded=True):
                            actual = chess.Move.from_uci(turns[ply-1]["uci"])
                            for observation in change_after_move(positions[ply-1], actual):
                                st.markdown("• " + observation)
                    if ply < len(turns):
                        with st.expander("Reveal what was actually played next", expanded=False):
                            st.write(f"{turns[ply]['number']}{'.' if board.turn else '...'}{turns[ply]['san']}")
                            st.caption("This is the historical game move, not necessarily the best move.")
                with right:
                    foundation = FOUNDATIONS[selected_phase]
                    st.markdown(f"### What are we trying to achieve in the {selected_phase.lower()}?")
                    st.markdown(foundation["goal"])
                    st.caption(foundation["why"])
                    st.markdown("**Think before choosing a move:**")
                    for q in foundation["questions"]:
                        st.markdown("• " + q)
                    with st.expander("Learn to read *this* board — both sides", expanded=True):
                        st.caption("These are board facts and prompts, not proof of a winning strategic plan.")
                        for observation in board_lenses(board, player_color):
                            st.markdown(f"**{observation['topic']}:** {observation['fact']}")
                            st.caption(observation["why"])

                lesson_id = f"{game_number}_{ply}"
                if "game_coach_reflections" not in st.session_state:
                    st.session_state.game_coach_reflections = {}
                if "game_coach_engine" not in st.session_state:
                    st.session_state.game_coach_engine = {}
                if "game_coach_lessons" not in st.session_state:
                    st.session_state.game_coach_lessons = {}
                if "game_coach_chats" not in st.session_state:
                    st.session_state.game_coach_chats = {}
                st.divider()
                st.markdown("### Your thinking → your coaching")
                st.caption("Say what you believe is going on. 'I'm not sure' is a useful starting point.")
                with st.form(f"game_reflection_{lesson_id}"):
                    last_move_effect = st.text_area("What changed, or what is the opponent threatening?",
                                                    placeholder="For example, their knight now controls e4. I'm not sure why that matters.", height=70)
                    target = st.text_area("What squares, pieces or weaknesses matter?",
                                          placeholder="Which piece needs improving? Which square could you use, and why?", height=70)
                    prospective_plan = st.text_area("What would your next 2–3 moves try to achieve?",
                                                    placeholder="I want to..., because...; the opponent may counter with...", height=70)
                    save_reflection = st.form_submit_button("Save my assessment", use_container_width=True)
                if save_reflection:
                    st.session_state.game_coach_reflections[lesson_id] = {
                        "last_move_effect": last_move_effect.strip() or "Not sure",
                        "priority_squares": target.strip() or "Not sure",
                        "candidate_plan": prospective_plan.strip() or "Not sure",
                    }
                    st.success("Assessment saved for this position. Now compare it with the evidence.")
                reflection = st.session_state.game_coach_reflections.get(lesson_id)
                if reflection:
                    st.caption("Your recorded plan: " + reflection["candidate_plan"])
                if lesson_id not in st.session_state.game_coach_engine:
                    if st.button("Check candidate moves with Stockfish", key=f"g_engine_{lesson_id}"):
                        try:
                            with st.spinner("Checking this moment more deeply…"):
                                st.session_state.game_coach_engine[lesson_id] = engine_checkpoint(
                                    board.fen(), engine_path, seconds=0.9)
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Stockfish couldn't analyse this position: {exc}")
                if lesson_id in st.session_state.game_coach_engine:
                    with st.expander("Engine evidence for this moment", expanded=False):
                        check = st.session_state.game_coach_engine[lesson_id]
                        for c in check["candidates"]:
                            st.markdown(f"**{c['move']}** · {c['score']} — {c['variation']}")
                        st.caption(check["note"])

                api_key = setting_from_secrets("OPENAI_API_KEY")
                access_code = setting_from_secrets("AI_COACH_PASSCODE")
                st.markdown("#### Ask your whole-game chess tutor")
                if not api_key or not access_code:
                    st.info("To use conversational lessons, add OPENAI_API_KEY and AI_COACH_PASSCODE in Streamlit Secrets. The replay and foundational prompts work without AI.")
                else:
                    if not st.session_state.get("ai_unlocked", False):
                        with st.form("full_game_unlock"):
                            code = st.text_input("AI coach access passcode", type="password")
                            if st.form_submit_button("Unlock tutor"):
                                if hmac.compare_digest(code, access_code):
                                    st.session_state.ai_unlocked = True
                                    st.rerun()
                                else:
                                    st.error("Incorrect passcode.")
                    if st.session_state.get("ai_unlocked", False):
                        context = teaching_context(
                            game, turns, positions, ply, player_color, reflection,
                            st.session_state.game_coach_engine.get(lesson_id), game_findings)
                        model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
                        if "game_coach_stories" not in st.session_state:
                            st.session_state.game_coach_stories = {}
                        st.markdown("#### The whole game, explained as a story")
                        st.caption("One complete review linking the opening, middlegame and ending. It checks a handful of chapter positions more deeply; it is not an engine audit of every move.")
                        if game_number not in st.session_state.game_coach_stories:
                            if st.button("Explain the strategy of my entire game", key=f"g_story_{game_number}",
                                         use_container_width=True):
                                try:
                                    with st.spinner("Checking the game's strategic checkpoints…"):
                                        chapter_evidence = chapter_engine_evidence(
                                            positions, landmarks, engine_path, player_color, seconds=0.4)
                                    story_context = dict(context)
                                    story_context["strategic_chapter_evidence"] = chapter_evidence
                                    with st.spinner("Building a phase-by-phase chess lesson…"):
                                        st.session_state.game_coach_stories[game_number] = ai_full_game_story(
                                            story_context, api_key, model=model)
                                    st.rerun()
                                except Exception as exc:
                                    st.error("Whole-game lesson could not be generated: " + str(exc))
                        else:
                            with st.expander("Your whole-game strategic lesson", expanded=True):
                                st.markdown(st.session_state.game_coach_stories[game_number])
                        st.divider()
                        st.markdown("#### Explore this position within the story")
                        if lesson_id not in st.session_state.game_coach_lessons:
                            if st.button("Teach me the theme and plans at this moment", key=f"g_lesson_{lesson_id}",
                                         type="primary", use_container_width=True):
                                try:
                                    if lesson_id not in st.session_state.game_coach_engine:
                                        with st.spinner("Grounding the lesson in Stockfish…"):
                                            st.session_state.game_coach_engine[lesson_id] = engine_checkpoint(
                                                board.fen(), engine_path, seconds=0.9)
                                        context["selected_position_engine_only"] = st.session_state.game_coach_engine[lesson_id]
                                    with st.spinner("Explaining how this fits into the game…"):
                                        st.session_state.game_coach_lessons[lesson_id] = ai_game_lesson(
                                            context, api_key, model=model)
                                    st.rerun()
                                except Exception as exc:
                                    st.error("Could not generate the lesson: " + str(exc))
                        if lesson_id in st.session_state.game_coach_lessons:
                            st.markdown(st.session_state.game_coach_lessons[lesson_id])
                            history = st.session_state.game_coach_chats.setdefault(lesson_id, [])
                            for msg in history:
                                with st.chat_message(msg["role"]):
                                    st.markdown(msg["content"])
                            with st.form(f"g_chat_form_{lesson_id}", clear_on_submit=True):
                                question = st.text_input("Challenge the tutor or ask about a concept",
                                                         placeholder="Why is d5 an outpost? What changed when the pawns exchanged?")
                                ask = st.form_submit_button("Ask my coach")
                            if ask and question.strip():
                                try:
                                    with st.spinner("Thinking through the concept…"):
                                        answer = ai_game_lesson(context, api_key,
                                                                question=question.strip(), history=history, model=model)
                                    history.extend([{"role": "user", "content": question.strip()},
                                                    {"role": "assistant", "content": answer}])
                                    st.rerun()
                                except Exception as exc:
                                    st.error("Question failed: " + str(exc))
                if st.session_state.game_coach_reflections:
                    st.download_button("Export my strategic reflections",
                                       json.dumps(st.session_state.game_coach_reflections, indent=2),
                                       file_name="my_strategic_chess_thinking.json", mime="application/json")
            else:
                st.info("No legal moves were found in this game.")

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
            size=490, coordinates=show_board_coordinates,
            colors=board_colors,
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
                    st.caption("Screening category (" + position.get("confidence", "unrated") + "): " + position["theme"] + ". " + position["explanation"])

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
                                   ("fen", "stage", "color", "game", "move_number", "theme", "loss_cp", "confidence", "explanation", "evidence", "question")},
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
                                  size=460, coordinates=show_board_coordinates, colors=board_colors)
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
            st.caption("Diagnostic confidence: " + selected.get("confidence", "Unrated"))
            st.markdown("**What to ask yourself:** " + selected.get("question", "Which move changes the position most?"))
            url = selected.get("game_url", "")
            if url.startswith("https://"):
                st.link_button("Open original game", url)
    st.caption("Note: Engine evaluation and pattern labels are approximations. Increase analysis time to verify borderline positions.")

with all_positions:
    st.subheader("All analysed mistakes")
    shown = df[["game", "date", "color", "move_number", "stage", "played", "best", "loss_cp", "theme", "confidence", "severity", "explanation"]].copy()
    st.dataframe(shown, hide_index=True, use_container_width=True)
    st.download_button("Download findings as CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name="my_chess_patterns.csv", mime="text/csv")
