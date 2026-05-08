# Scope — Locked Week 1

## MUST HAVE (v1)
- [ ] Dataset validation (CICIDS2017 schema check)
- [ ] Pipeline 1: RF + RFE (Sharafaldin et al. 2018)
- [ ] Pipeline 2: DT + CFS (Jaradat et al. 2022)
- [ ] SQLite experiment tracking
- [ ] Artifact saving (model.pkl, metrics.json, metadata.json)
- [ ] Streamlit UI (run experiment, view history, environment info)
- [ ] Reproducibility (same input → identical output)
- [ ] CLI runner for manual testing

## NICE TO HAVE (v2 — only if ahead of schedule)
- [ ] Pipeline 3: MLP (UNSW-NB15)
- [ ] Celery + Redis async execution
- [ ] Docker containerization
- [ ] UNSW-NB15 dataset support

## OUT OF SCOPE
- Real-time / streaming detection
- User-configurable hyperparameters
- Multi-user authentication
- Cloud deployment
- GPU training
- LSTM / deep learning pipelines
