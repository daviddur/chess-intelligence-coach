# Upgrade to v0.4 — Whole-game coach

This version expands Chess Intelligence Coach from isolated critical positions into guided, phase-aware whole-game replay.

## If v0.3 already works on Streamlit Community Cloud

1. Download and extract `chess_coach_v04_update_only.zip`.
2. Open your GitHub repository `chess-intelligence-coach`.
3. Upload **both** `app.py` and `game_coach.py` to the repository **root** (the same level as `concept_coach.py`, `analysis.py`, and `requirements.txt`).
4. Commit the changes, replacing the old `app.py`.
5. Once Streamlit redeploys, run `Analyse my games` again. This is necessary because the PGNs need to be available to the new replay feature within the live Streamlit session.
6. Open the **Whole-game coach** tab. Pick a game and jump to its strategic chapters, or use Previous/Next to replay any move.
7. Write a reflection. You can reveal the next move, check 3 engine candidates for a chosen moment, or generate a conversational lesson using your existing OpenAI key and passcode.

## What v0.4 changes

- Replays the *entire* game, including opponent moves.
- Adds an introductory conceptual guide: threats, important squares, worst piece, pawns and plan.
- Creates a small set of strategic chapters from opening, phase changes and detected critical decisions.
- Explains observable square control, pawn-supported squares, king placement, activity, open files and what the last move changed.
- Sends the **whole game history** (plus selected board, reflections and local engine check) to the AI coaching layer.
- Keeps the original **Weakness profile**, **Understand a position**, **Tactic practice** and **All findings** tabs.

## Limitations

- The AI coach is not an authoritative chess engine; some strategic explanations can still be wrong. Engine evaluations are based on a short search of the *selected* position only.
- Strategic chapters are heuristic and will not catch every important turning point.
- Replay and reflection history are stored in Streamlit's session memory. Export your reflections to keep them beyond app restarts. Permanent accounts, persistence and spaced repetition are future work.
- The board is visual and navigable with Previous/Next and a slider; direct piece dragging is not implemented.
- The opponent's or your motivation for a move cannot be inferred from the move alone. The app teaches reasonable, conditional plans, not mind-reading.

## Security and billing

Keep `OPENAI_API_KEY` and `AI_COACH_PASSCODE` in Streamlit Secrets, **never** in this GitHub repo. The app makes AI calls only when you explicitly click a tutoring action or send a question. Your API key is billed separately from ChatGPT Plus.

## New in the strategic-story mode

After unlocking the existing AI tutor, click **Explain the strategy of my entire game**. It checks up to seven chapter positions (short Stockfish searches), then generates one phase-by-phase narrative covering both players' goals, changing position themes and practical habits. The cost is one AI request per game, initiated only when you click the button.
