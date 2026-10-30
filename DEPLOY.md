# Deploy Chess Intelligence Coach on Streamlit Community Cloud

No Python installation or command line required to deploy online.

## 1. Create a free GitHub repository

1. Sign in to https://github.com
2. Open https://github.com/new
3. Repository name: `chess-intelligence-coach`
4. Select **Public** for the simplest first deployment, then click **Create repository**.

## 2. Upload these files

1. Unzip `chess_coach_streamlit_ready.zip` on your computer.
2. Inside the extracted folder, select **all** the files (not the folder itself and not the ZIP).
3. In your GitHub repository, use **Add file → Upload files**.
4. Drop the files onto GitHub and click **Commit changes**.

Your GitHub repository must have this structure (no extra nested folder):

```
chess-intelligence-coach/
  app.py
  analysis.py
  coach.py
  collector.py
  requirements.txt
  packages.txt
  README.md
  DEPLOY.md
```

Do not add passwords, tokens, or API keys to GitHub.

## 3. Deploy in Streamlit

1. Sign in with GitHub at https://share.streamlit.io
2. Select **Create app** (or **New app**, depending on the UI).
3. Choose **Yup, I have an app**, if asked.
4. Repository: `YOUR_GITHUB_USERNAME/chess-intelligence-coach`
5. Branch: `main`
6. Main file path: `app.py`
7. Deploy.

Streamlit installs the Python dependencies in `requirements.txt` and the Stockfish Linux system package listed in `packages.txt`.

## 4. Analyse your first games

1. In the app sidebar, select **Chess.com** (the default).
2. Leave the username as **dav4life**.
3. Set **Recent games to scan** to **10** to check that it runs.
4. Leave engine time at 0.08 seconds per position initially.
5. Click **Analyse my games**.
6. Open the **Understand a position** tab, write your plan, and submit a legal candidate move in SAN (e.g. `Nf3`) or UCI (`g1f3`) notation.
7. When that works, analyse 30 games and compare the error patterns.

The generated explanations in this version are **board-feature prompts and engine data**, not a fully conversational AI coach. The board displays positions but does not yet support dragging pieces; type your move instead.

## Troubleshooting

- **`No module named chess` / dependencies fail:** Verify `requirements.txt` is next to `app.py` in GitHub.
- **`stockfish` not found:** Verify `packages.txt` is next to `app.py` and contains only the word `stockfish`. Check the sidebar's engine path; on Streamlit Cloud it should often be `/usr/games/stockfish`. In Streamlit's app settings, reboot after dependency changes.
- **Chess.com API error:** Confirm your public username and availability of recent rapid games. You can also export games as a PGN and select the **PGN upload** source. PGN imports are not automatically filtered by rapid time class.
- **App is slow:** First analyse 10 games with the 0.05 or 0.08 seconds/position setting, then increase the number of games.
- **Can't enter a move by clicking the board:** This release takes typed SAN or UCI. A click-to-move chessboard is planned but not implemented.
- **GitHub says it cannot find `app.py`:** The Python files were probably uploaded inside an extra folder. Move them to the repository root, or change Main file path to the nested path.

## Local run (optional)

On macOS, after installing Python 3.10+ and Stockfish (for example with Homebrew):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Community Cloud's free resources and CPU limits can affect analysis speed. Store no secrets in a public repo. The app only fetches public Chess.com game history and does not need your Chess.com password.
