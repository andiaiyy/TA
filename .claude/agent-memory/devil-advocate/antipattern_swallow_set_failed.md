---
name: Bare except around set_failed loses terminal status updates silently
description: Wrapping the FAILED state-write in `try/except: pass` means a stuck experiment is undetectable from logs.
type: feedback
---

Pattern observed in `experiment_service.create_and_run_experiment` and `celery_worker.run_pipeline_task`:
```
except Exception:
    try:
        set_failed(...)
    except Exception:
        pass
```

Risks:
- If `set_failed` itself raises (DB lock exhaustion, disk full, schema drift), the experiment stays in RUNNING/QUEUED forever and there is **no record** that anything went wrong.
- The cleanup-on-startup is the only safety net, and it is time-thresholded (default 120 minutes) — so a UI in a tight rerun loop won't see the failure for up to 2 hours.
- No structured logging of the inner exception means even post-mortem debugging is blind.

**Why:** "Don't crash on cleanup" is a reasonable instinct but the swallow-and-forget version is worse than letting Celery's task ack mechanism see the failure.

**How to apply:** Whenever you see a bare `except: pass` around DB state transitions, demand at least a `logger.exception(...)` and ideally a fallback (write a sentinel file, push to Redis, etc.).
