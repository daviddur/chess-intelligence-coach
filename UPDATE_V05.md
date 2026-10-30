# v0.5 — Explain the unexplained evaluation losses

This fixes the old **Other evaluation losses** catch-all in the Weakness profile.
The app still cannot magically infer a player's intentions from moves, so it
separates evidence from hypotheses and allows deeper engine checking.

## What to upload to GitHub

Upload these **FOUR files** into the **root** of your existing GitHub repository:

- `app.py` — replace (includes earlier v0.4 whole-game coach + board colour themes)
- `analysis.py` — replace
- `game_coach.py` — replace
- `diagnosis.py` — **new**

Do **not** delete `coach.py`, `concept_coach.py`, `collector.py`, `requirements.txt`,
`packages.txt` or any other pre-existing files. Your Streamlit Secrets (API key,
passcode) do not need to change.

Commit the files. Streamlit redeploys from GitHub. Run the game analysis again,
as the new scan produces more diagnostic fields and redeploy can reset session state.

## How to use it

1. Open **Weakness profile** after scanning games.
2. Look at **Supported consequences**, **Strategic / tactical hypotheses**, and
   **Needs deeper investigation**. These have different certainty levels.
3. Expand **Investigate inconclusive decisions with deeper Stockfish analysis**.
4. Recheck one position or a batch of five with 1.5 seconds per side of the decision.
5. Inspect the move's actual evidence and learning question. Repeat for another
   batch if you want to investigate more decisions.
6. If a deeper engine search overturns the original fast evaluation, the app
   removes that mistake from the weakness profile and exercise queue.

The new categories include visible material swings in engine lines, possible
opening development and king safety issues, possible central pawn breaks,
knight outpost ideas, and endgame king activation. A **candidate** is not proven
just because Stockfish prefers a move with that feature.

### Limits

- The scan remains a fast, approximate engine screen. A threshold of 75 cp with
  0.08 seconds per position can include noisy evaluations. Use a longer engine
  interval or deeper rechecks for important decisions.
- Some decisions correctly remain **Needs deeper investigation**: the app
  prefers acknowledging uncertainty to inventing a lesson.
- Rechecking many positions may take time on the free Streamlit server.
- These files have been syntax-checked but were not run against the installed
  `python-chess` library or Stockfish in the isolated packaging environment.
