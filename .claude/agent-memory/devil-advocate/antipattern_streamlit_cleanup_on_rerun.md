---
name: Streamlit module-top-level work runs on every rerun
description: Streamlit re-executes the script on every widget interaction — anything at module top level (DB writes, cleanup, network calls) fires repeatedly.
type: feedback
---

Streamlit's execution model re-runs the entire script top-to-bottom for every user interaction (button click, text input change, page nav). Code at the top level of `app.py` (and views) runs every single time.

Implications to flag in reviews:
- "Startup cleanup" placed at module top is NOT startup — it's per-interaction. Multiple users + multiple clicks = N writes per second, all racing on the same DB.
- `init_db()` at top level: cheap but still ~1ms IO per click.
- Reads of large directories, network probes (e.g., redis.ping), or file scans should be wrapped in `@st.cache_data` / `@st.cache_resource` or moved out of the hot path.
- Any function with side effects on the DB called at top level needs idempotency *and* concurrency protection.

**Why:** Common foot-gun for engineers new to Streamlit. The "startup" mental model from Flask/FastAPI does not transfer.

**How to apply:** Whenever reviewing Streamlit code, scan for top-level code with side effects. Push for `st.cache_resource` for one-shot setup, or for moving the work to an explicit migration script run before the app boots.
