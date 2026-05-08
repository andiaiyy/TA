---
name: IDS Research Pipeline — project context
description: Thesis project — Streamlit UI dispatching 7 fixed ML pipelines (1 CICIDS2017, 6 HIKARI2021) sync or via Celery+Redis, persisting to SQLite + JSON artifacts.
type: project
---

Streamlit web app for an IDS research thesis. User uploads a CSV, picks a fixed pipeline, runs it locally (sync) or via Celery+Redis (async). Results in SQLite plus per-experiment JSON+pickle artifacts under `storage/artifacts/<id>/`.

**Why:** This is a *thesis* — reviewer scrutiny is academic (reproducibility, leakage, statistical validity), not just engineering. Bar for production-readiness is lower than enterprise SaaS but bar for *methodological correctness* is higher.

**How to apply:** When reviewing, weight scientific validity (data leakage, biased evaluation, reproducibility, dataset hash integrity) at least as high as ops concerns. Don't dismiss prod-readiness gaps but recognize the *primary* risk is publishing invalid results, not 3am pages.
