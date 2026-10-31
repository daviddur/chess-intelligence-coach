# v0.6 — Live Chess Lesson (replacement for Whole-game Coach)

## Install into your existing Streamlit GitHub repository

1. Extract `chess_coach_v06_live_update.zip` on your computer.
2. Go to your GitHub repository `chess-intelligence-coach`.
3. Upload `app.py` (replace existing), `live_tutor.py` (new), and `requirements.txt` (replace existing) **at the repository root**. Keep the other files unchanged.
4. Commit changes. Streamlit redeploys automatically.
5. If the app shows an import error after redeployment, make sure `live_tutor.py` is at the same level as `app.py`, and that `game_coach.py`, `analysis.py`, `diagnosis.py`, and `concept_coach.py` are still present.

## Test the new experience

1. Run a **1-game analysis** (or reuse a current session, if retained).
2. Open **Live chess lesson** (replaces Whole-game Coach).
3. Unlock the tutor using your existing passcode; your OpenAI key and secret settings remain unchanged.
4. Click **Start my chess lesson**. It should ask ONE game-specific question, not dump a long report.
5. Answer in the chat, or record a response using the microphone and select **Send voice message**.
6. Try **Help me find a plan**. The coach should describe a concrete candidate objective for both sides, not only the engine's best move.
7. Click **Next teaching moment**. The board changes and the coach should ask a new question about that moment.
8. Optional: select **Play coach's answer** for text-to-speech. This incurs extra API use.

## Notes and limitations

- This version is **push-to-talk**, not continuous hands-free voice. Microphone access must be allowed by your browser.
- Text and voice history persist only within the Streamlit session; they do not yet survive browser-session loss or app restart.
- It uses short Stockfish searches to ground coaching; explanations are still model-generated, so test surprising claims against board evidence.
- AI requests, speech transcription, and optional speech playback incur OpenAI API charges.
- The `gpt-4o-mini-tts` speech model is scheduled for retirement on **January 6, 2027**; this optional playback feature will need a newer audio architecture before then.
- Don't paste your API key into GitHub or screenshots. Keep it in Streamlit Secrets as before.
- Local testing of the complete Streamlit/Stockfish/API flow was not possible in this environment; static and isolated API-call tests were performed.
