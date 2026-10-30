# Chess Intelligence Coach — Streamlit-ready version

**Fastest route:** Read [`DEPLOY.md`](DEPLOY.md) for the browser-only GitHub → Streamlit Community Cloud setup.

The app defaults to Chess.com username `dav4life`. `packages.txt` installs Stockfish on Streamlit Community Cloud, and the sidebar automatically detects its standard Debian path `/usr/games/stockfish`.

---

# Chess Intelligence Coach — Guided Review Prototype (v0.2)

A personalised, engine-grounded chess review app for **Chess.com username `dav4life`**. Its first job is to help you *reason about a position* before showing engine moves. It uses publicly accessible Chess.com monthly game archives and filters specifically for **standard rapid games** (not blitz or bullet).

## Quick start

Install Python 3.10+, [Stockfish](https://stockfishchess.org/download/) and the Python packages:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Choose **Chess.com** and leave the username **dav4life**. Start with 10 games to check things work; then increase to 30. The Stockfish executable must be on PATH or configured in the sidebar. `packages.txt` contains `stockfish` for compatible Linux hosting environments.

**No Chess.com login or password is needed.** The app reads the public archive. It does not have access to private games.

**Fallback:** If the API is blocked on your network, in Chess.com use *Game History → select games → Download PGN*, choose **PGN upload**, and set your username. When using PGN upload, the input must itself be restricted to rapid if you want a rapid-only data set.

## What's new in v0.2

- **Rapid-only imports:** Reads monthly archives newest-first and selects `time_class=rapid` and `rules=chess`, skipping duplicates, stopping after the selected count.
- **Five guided critical-position reviews:** Selects a variety of detected costly decisions, preferring different stages/games.
- **Four-step thinking capture:** You must choose a priority, name opponent counterplay, formulate a plan, and make a legal candidate move *before* the engine answer appears.
- **Inspectable positional evidence:** Shows material, centre pawns, opening development, potential hanging pieces, pawn structure and available checks, with questions about why each matters.
- **Engine-grounded comparison:** Original move, preferred move, principal variation, and best opponent reply after the original move.
- **Reasoning export:** Download your responses as JSON to compare across training sessions.

## What is *not* built yet

- Not a full LLM coach. The current position evidence consists of mechanically calculated board facts and review prompts. A future language-model layer should compose a richer strategic explanation **only using verified board facts and engine lines**, and explicitly qualify uncertain claims.
- Not an exact tactical-motif classifier. The fork/pin/skewer and other motif names are heuristic hypotheses which may include errors. They need validation and better engine lines before forming high-confidence personalised diagnoses.
- Not a validated diagnosis of a thinking mistake. A move doesn't reveal what you were thinking. That is why the guided review asks you to record your reasoning.
- Not yet a persistent spaced-repetition or user-authenticated system. Results are kept in the browser session, with manual JSON export.
- Not a complete web-chessboard editor. The board renders a legal FEN and the user submits candidate moves in standard chess notation (SAN) or UCI, with legality checked.

## Product plan (the next three milestones)

### M1 — Reliable collection and game triage

**Input:** Recent 30 standard Chess.com rapid games for `dav4life`, wins and losses. Deduplicate using game URL; store original PGN, colour, result, date, stage, move number and position FEN.

**Processing:** Evaluate each player decision with Stockfish, then perform a longer second pass on important moments. Store raw engine data, including the best line and the response to what was actually played. Use an *opportunity-level denominator*: of the situations with a verified tactical theme, how many were missed? Avoid conflating volume of errors with weakness.

**Acceptance:** Exactly 30 rapid PGNs (if there are enough available), zero other time classes, engine lines legal, every finding navigable back to its original Chess.com game.

### M2 — Conceptual lesson engine

**Input:** An engine-confirmed position + board features + pawn structure + player self-report.

**Review protocol:**
1. Hide the answer. Ask what's threatened, which imbalances matter, and what's the plan for *both* sides.
2. Have the player submit a candidate move and explanation.
3. Compare candidate lines (not just top-one), verify strategic assertions against the board and PV, explain *what changes* after each move.
4. Teach a transferable principle: e.g., an attack without enough pieces, trapped minor pieces, a favourable pawn break, loose pieces on an open file, when simplification helps.
5. Finish with one recognition cue and a mini-quiz.

**Acceptance:** A reviewer can point to board facts or a concrete PV supporting every claim. The app distinguishes direct tactical refutations from strategic, longer-term positional concessions.

### M3 — Profile and deliberate practice

Group validated missed opportunities by tactical **motif**, positional **concept**, stage, and situation. Save answers as behavioural evidence; identify self-reported uncertainty separately from observed engine mistakes. Create 5–10 minute daily sessions with retrieval practice, spaced repetition and post-training retests. Progress should measure **recognition and correct reasoning in new positions**, not just memorising the original game.

**Acceptance:** A player can answer 'Which three positional concepts most limit my rapid play?' with traceable evidence across games and quantify performance on new but similar positions.

## Architecture

`Chess.com public archives` → `rapid-only collector.py` → `python-chess PGNs` → `Stockfish` → `engine findings (analysis.py)` → `verified feature extraction (coach.py)` → `guided position review (app.py)` → `reasoning JSON export`.

## Accuracy / licensing notes

Chess.com public data is read-only and subject to Chess.com's API and branding policies. This repository does not include the Stockfish binary; distributing it requires complying with its GPLv3 licence. Deep engine analysis requires computing time. No external AI API key is required for the prototype.
