# Engine lab, lab-learn: learning approaches (2026-11-24)

Branch `lab-learn` (worktree `C:\Users\marco\Developer\pokemon_go-lab-learn`), from `engine-lab`; commits 6d1cebfd and
19deb0c7. Everything is opt-in: new files under `pogo/lab/`, `scripts/lab/`, `runs/lab-learn/`, and new keys in
`scripts/engine_versus.py`. No default, shipped network or website setting changed. The full suite: 433 tests, only the
3 expected `test_form_icons` OCR errors; `scripts/check_pvpoke.py`: 108 of 108.

## The problem, as the earlier results put it

- Every q since task 19 was trained and judged against our own bots. The best changes are worth 1–4 points head to head
  against the shipped bot (task 19: 53.6%; both sides kept: 52.6%); exploiters reach 51–55% against their own target only
  (task 14). New q networks lost inside the website engine: task 39 48.6% then 46.9%; task 44 41–43%; task 48 48.1%, and
  51.1% without mid_swap.
- The engine's strength is mostly exploiting the opponent it imagines (`docs/benchmarking.md`: +17 against the trained
  bot, about −2 against PvPoke's AI). The website engine imagines its opponent as the trained bot, on the same q it uses
  for its own side. When q changes, the imagined opponent changes with it although the real opponent has not. That had
  not been tested.
- The website engine departs from the trained bot at about 13% of its decisions (task 39), driven by a stochastic search;
  to an opponent it looks like a mixed strategy around the bot.

## Approaches considered

| Approach | Verdict |
|---|---|
| Population / PSRO-lite training of q (fictitious play with averaging: past networks, varied rulebook, person-like players, both sides kept, PvPoke 1v1) | Built (`scripts/lab/train_population.py`), smoke-tested, long run proposed |
| Keep the engine's own network apart from the opponent it imagines; a learned model of the website engine as that opponent | Built (`pogo/lab/engines.py`, `fit_policy.py engine`). Measured at proxy strength: the imagined opponent is worth about 5.6 points; the learned engine model does not beat the plain bot as that model |
| piKL: the bot's values + lam × log P(a person makes this choice) | Built (`PolicyPlayer(anchor=, lam=)`, anchor fitted on the owner's games); neutral at lam 0.03, worse at 0.1 |
| A fitted people model (task 42) | Built as an imitation policy of the owner, used as a judge and as an imagined opponent. Task 42's fit of the rulebook's genes is left to lab-creators |
| Calibrated policies, sampled (mixed strategies) | Built (`PolicyPlayer(pnet=, sample=True)`); the sampled engine policy as a bot alone loses badly. Mixing inside the engine is lab-mixed's work |
| q trained against the website engine (an exploiter) | Only its cost measured: an engine opponent makes example collection 12–20× slower. Not proposed |
| Bigger network, more inputs | Not tried; status.md: "Is the network too small? No"; "Does the bot need to see their other Pokémon? Predicts better, plays the same" |
| A KL pull inside the q loss | Not built: 1,021 owner decisions against millions of play-out examples, and task 39 showed the q heads copy almost none of a minority signal; a separate anchor (piKL) is the cleaner form |

## What was built

- `pogo/lab/policy.py`: `PolicyNet` per decision kind (shield 2 options, throw 3, swap 3, replace 2) on the bot's 45
  inputs plus the trained bot's own pick (one-hot, `bot_input`); 64 (or 16) rectifiers then softmax; `fit` (Adam,
  cross-entropy, row weights, L2), `save`/`load`, `cached`. `PolicyPlayer(Learner)`: `pnet` plays a policy (likeliest, or
  drawn with `sample=True` from a separate generator); `anchor` + `lam` is piKL (score = q value + lam × log anchor
  probability; overrules the rulebook only by the margin; lam 0 plays exactly as the trained bot); `temperature` > 0
  draws from softmax(score / T).
- `pogo/lab/engines.py`: `ModelledEngine(RealTime)`: `opp_q` makes the imagined opponent the trained bot on those
  networks while our side keeps `q`; `opp_policy` makes it play a PolicyNet (drawn by default, `opp_sample`). Only with
  `opponents="bot"`. With `opp_q` equal to q it plays as the engine (tested).
- `scripts/engine_versus.py` keys (additive; `bot` and `website` unchanged): engine `opp_q=PATH`, `opp_policy=PATH`,
  `opp_sample=0|1`; bot alone `q=PATH`, `margin=`, `policy=PATH`, `sample=0|1`, `anchor=PATH`, `lam=`, `temperature=`.
- `scripts/lab/fit_policy.py`: `engine` fits the website engine's picks in task 39's round 1 self-play (554,063 decisions
  of 10,000 games, read from `C:/Users/marco/Developer/pokemon_go/runs/engine-loop/round_1/games`, games 0 mod 10 held
  back); `owner` fits Luke's choices from his 35 website games replayed exactly with the trained bot watching his side
  (the 22 decisions on the exam's held-out turns never used; 5 game-wise folds, then all games).
- `scripts/lab/train_population.py`: decide.py's per-decision learning with each example battle's opponent drawn from a
  weighted population (`rulebook`: the varied crowd; `past`: the shipped q, q_v1–q_v5, task 39's rounds and every
  generation so far at margins 0.02/0.05/0.1; `people`: the bot with `human_settings` and the creators' shield calls;
  `imitation` and `engine` off by default), plus `--both-sides 0.2` and `--pvpoke-share 0.05`. Each generation is
  collected with the newest network as pilot; a fresh network is fitted on all examples so far (fictitious play's average
  best response) and joins the population. No mid_swap head; margin 0.02. `--check N` after each generation; resumes after
  its last finished generation.
- `scripts/lab/versus_people.py`: specs against person-like opponents on the same battles, paired against the first
  spec: `human` (the bot with `human_settings` and the creators' shield calls), `owner` (the owner's imitation policy,
  drawn), `owner_top` (its likeliest option).
- `tests/test_lab_learn.py` (11 tests, under a second).

## Results (at most 2 workers)

### 1. The imagined opponent decides the engine's head-to-head result (proxy)

`engine_versus.py`, baseline `website,samples=8`, seed 7211, mixed field, head to head only (`runs/lab-learn/proxy8-oppq*.out`).

| Engine (all samples=8) | Own network | Imagined opponent | Head to head against website |
|---|---|---|---|
| `q=runs/engine-loop/round_2/q.npz` (as task 39 used it) | round 2 | round 2 | 44.2% ± 4.7 (160 pairings) |
| `q=round_2,opp_q=runs/general-decide/q.npz` | round 2 | shipped | **49.1% ± 3.3** (320) |
| `opp_q=round_2` | shipped | round 2 | **43.4% ± 3.1** (320) |

Paired on the same 320 pairings: own round 2 with the shipped opponent minus shipped own with the round 2 opponent,
**+5.6 ± 4.3**; coupled against decoupled on 160 pairings +5.0 ± 5.7. The loss comes from changing the opponent the
engine imagines; round 2 as its own network costs nothing measurable. This is the likely reason new q networks lost
inside the engine in tasks 39 and 48 (task 44's candidates also carried a mid_swap head). Screen any new q with
`opp_q=runs/general-decide/q.npz`. A proxy at a quarter of the samples: screen A confirms it at full strength.

### 2. The website engine as a policy (`runs/lab-learn/engine-policy/`)

| Kind | Decisions | Engine departed from the bot | Likeliest = engine's pick: policy / bot | Log loss: policy / bot at its departure rate | Departure AUC |
|---|---|---|---|---|---|
| throw | 35,109 | 15.0% | 85.0% / 85.0% | **0.450 / 0.487** | 0.69 |
| swap | 8,620 | 16.1% | 83.7% / 83.9% | **0.421 / 0.520** | 0.79 |
| replace | 1,922 | 24.1% | 75.9% / 75.9% | 0.551 / 0.554 | 0.56 |
| shield | 9,129 | 0% (the website does not search shields) | 100% / 100% | – | – |

Where the engine is likely to override is learnable and calibrated (throws: predicted 0–5 / 5–10 / 10–20 / 20–30 /
30–50% → actual 3 / 8 / 17 / 24 / 37%; swaps 1 / 8 / 15 / 24 / 35%, and 51% where 50%+ was predicted); which option it
picks is not. As the imagined opponent (`website,samples=8,opp_policy=...`, 300 pairings, seed 7201): 49.0% ± 3.2, search
seconds per battle 1.23 against 0.99: no gain. Caveat: round 1 used the evaluation of the time, not task 47's wide one.

### 3. The owner as a policy (`runs/lab-learn/owner-policy/`, 1,021 decisions, 5 game-wise folds)

| Kind | Decisions | Owner departed from the bot | Likeliest = owner's: policy / bot | Log loss: policy / bot |
|---|---|---|---|---|
| throw | 661 | 36.3% | **67.5% / 63.7%** | **0.728 / 0.853** |
| swap | 157 | 34.4% | **72.6% / 65.6%** | **0.698 / 0.802** |
| shield | 170 | 28.2% | 72.9% / 71.8% | 0.556 / 0.598 |
| replace | 33 | 42.4% | 57.6% / 57.6% | 0.787 / 0.725 |

Agrees with `scripts/people_model.py` (66% against 62%). As a player it is weak: the trained bot beats it 85.1% ± 3.5
(drawn) and 85.0% ± 3.5 (likeliest), 400 battles each; the bot beats the `human` style 61.4% ± 4.8. Many of the owner's
departures are "hold one more turn", which real-time reaction also produces: a weak person-like opponent, not a model of
the owner's strength.

### 4. Cheap screens on bots (`versus_people.py`, seed 6001, mixed field, paired points on `bot`)

| Bot | vs human | vs owner (drawn) | vs owner (likeliest) |
|---|---|---|---|
| `bot` (baseline, 400 battles per kind) | 61.4% ± 4.8 | 85.1% ± 3.5 | 85.0% ± 3.5 |
| `bot,anchor=owner-policy,lam=0.03` (200 per kind) | +0.5 ± 5.2 | +2.8 ± 5.3 | – |
| `bot,anchor=owner-policy,lam=0.1` | **−9.0 ± 5.0** | −6.9 ± 4.5 | −6.5 ± 4.2 |
| `bot,q=runs/general-decide/q_v5.npz` (control) | −0.4 ± 4.8 | +0.4 ± 3.7 | +2.1 ± 3.7 |
| `bot,policy=engine-policy,sample=1` (200 per kind) | **−14.0 ± 7.3** | −6.8 ± 7.2 | – |

piKL with this anchor is neutral at small lam and costly at larger lam. The engine's sampled policy as a bot alone loses:
its departures are only right together with the search's information, so it is an opponent model, not a player.

### 5. Population training smoke (`runs/lab-learn/smoke`, 2 workers, 2 generations of 1 minute)

487 and 458 battles; about 7,400 and 6,950 examples a generation (about 3,700 per worker-minute). Checks, 60 pairs both
ways: 30.8% ± 8.7 and 36.7% ± 7.3 head to head against the shipped bot; −20.0 ± 15.3 and −12.5 ± 13.3 against the crowd —
expected with about 0.1% of the shipped network's examples. The pipeline works: resume, checks, the population grows.

## Proposed long runs (8 workers each; LF; one line each)

| File | What | Workers | Time | Produces |
|---|---|---|---|---|
| `runs\lab-learn-screen-a.cmd` | Opponent-model diagnostic at full strength: baseline website; candidates `website,q=round_2`, `website,q=round_2,opp_q=shipped`, `website,opp_q=round_2`; 1000 pairings both ways, 500 crowd, 250 PvPoke, seed 7301, mixed field | 8 | ~3 h | `runs/lab-learn-screen-a.out` |
| `runs\lab-learn-population.cmd` | Population training: 3 generations, 180 min of collection, `--check 2000`, then `train_eval.py --wide --battles 40000` on the new q | 8 | ~4 h | `runs/lab-learn/population/q.npz`, `gen_{1,2,3}/q.npz`, `eval.npz`, `training.json`, `runs/lab-learn-population.out` |
| `runs\lab-learn-screen-b.cmd` | After the population run: bots `bot` vs `bot,q=population` and `gen_1` (4000/4000/2000, seed 7402), then the people judge (3000); engines website vs `website,q=pop,opp_q=shipped`, `website,q=pop`, `website,q=pop,opp_q=shipped,opp_policy=engine-policy` (1000/1000/500, seed 7401), then the people judge (1500) | 8 | ~4 h | `runs/lab-learn-screen-b.out` |
| `runs\lab-learn-people-engine.cmd` (optional) | Website vs `website,opp_policy=owner-policy` and `opp_policy=engine-policy` against the `human` style (1500 battles), then head to head against website (500 pairings) | 8 | ~1.5 h | `runs/lab-learn-people-engine.out` |
| `runs\lab-learn-website-games.cmd` (optional) | 2000 games of today's website engine against itself, then the engine policy refitted on them | 8 | ~1 h | `runs/lab-learn/website-policy/policy.npz` |

Order: screen A and the population run side by side (16 threads), then screen B.

## How to judge

- Against our current engines (the goal): `engine_versus` head to head against `website`, and the bot alone against `bot`;
  the usual rule (above 50% beyond the margin, no worse than the margin against the crowd and PvPoke, confirmed on a
  fresh seed with 2000 pairings). Report search times (`opp_policy` costs about 24% more search per battle at the proxy).
  Screen every new q inside the engine with `opp_q=runs/general-decide/q.npz`.
- Against person-like opponents (`versus_people.py`), only the fair judges: population q — owner, owner_top, the exam
  (not human: the `people` training kind is that style); `website,opp_policy=engine-policy` — human, owner, owner_top, the
  exam; `website,opp_policy=owner-policy` and `bot,anchor=owner-policy` — human and the exam (not owner/owner_top).
- The exam on the owner's Mac is the real people judge; score any candidate there before adoption.
- Review battles, not only rates: engine_versus's per-battle counters, and how often each engine departs from the bot.

## Open questions

- Does the imagined-opponent effect hold at 32 samples (screen A)? If it does, the engine's result rests on modelling the
  opponent; against people that points to a better people model (task 42) as the lever, more than a better q.
- Does a population-trained q gain inside the engine once the imagined opponent stays the shipped bot (screen B)?
- A better people anchor or people opponent needs better data; the creators' battles could become a `fit_policy.py`
  source (`scripts/real_decisions.py` already rebuilds their positions).
