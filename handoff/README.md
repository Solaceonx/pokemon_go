# Hand-off briefs

Self-contained briefs for agents, some written for agents that could not see this repository. For work
inside the repository, start from [`../docs/tasks.md`](../docs/tasks.md) instead: it lists every task with
its state, and [`../docs/status.md`](../docs/status.md) has every result.

| File | What it asks for | State (2026-10-14) |
|---|---|---|
| `agent_instructions.md` | An agent watching battle videos and writing down "looks" by hand (task 2) | Superseded by the automatic pipeline in `scripts/recording/`; kept for footage that pipeline cannot read. Same text as `docs/agent_instructions.md` |
| `pvpoke_port_instructions.md`, `pvpoke_port_bundle.zip` | Port PvPoke's battle AI to Python (task 6) | **Done**: `pogo/pvpoke_ai.py`, 108 of 108 (`scripts/check_pvpoke_ai.py`) |
| `vod_pipeline_instructions.md`, `tracker_bundle.zip` | Feed recordings through the pipeline in bulk and make it cope with new footage | Largely done (the owner's recordings, Twitch and official VODs; whole-recording extraction is task 22). Its "known to break" list is from 10 October |
| `vod_readings_request.md` | Publish the readings of the reserved official sample and run the frozen test | **Done** (task 17; `docs/reserved_state_evaluation.md`). The reserved clips stay reserved: do not tune on them |
