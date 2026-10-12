# pokemongo · Match 01 · right · partial

Source: https://www.twitch.tv/videos/2897295240
Source interval: 0.000-23.500 seconds.
Match: `tw-2897295240-match-001`; view: `right`; dataset: `exposed_regression`.

Read all saved clip time: 353 samples at 15 Hz, text at 3 Hz; 14 reconstructed model states.
Partial beginning: True; partial ending: False.

Screen evidence includes names/CP, health bars, shields, party markers and visible controls.
Bars can be absent or unsettled during attacks; compression, short sprites and broadcast overlays limit readings.
HP remains a fractional interval. Maximum/integer HP, form and unseen roster are unverified.
Fast moves, modeled energy, stages and switch timing are hypotheses, not screen observations.

| Side | Visible health samples | Missing health samples | Estimated energy samples |
|---|---:|---:|---:|
| mine | 84 | 269 | 41 |
| opponent | 63 | 290 | 0 |

Internal consistency: **fail**.

- ending: result says win, tracker has us on 1 and them on 1
- coverage: clip starts mid-match; initial energy, shields and team history are unknown

Recognition accuracy has not been measured against independent human labels.
The ledger retains unaffected readings during animations. Affected values are pending until fresh evidence resolves them.
Old readings for a fainted Pokemon are historical. Unknown initial values remain unknown.
A final announcement does not fabricate zero HP or a knockout.
