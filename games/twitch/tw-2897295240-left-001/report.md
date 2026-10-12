# pokemongo · Match 01 · left · partial

Source: https://www.twitch.tv/videos/2897295240
Source interval: 0.000-23.500 seconds.
Match: `tw-2897295240-match-001`; view: `left`; dataset: `exposed_regression`.

Read all saved clip time: 353 samples at 15 Hz, text at 3 Hz; 13 reconstructed model states.
Partial beginning: True; partial ending: False.

Screen evidence includes names/CP, health bars, shields, party markers and visible controls.
Bars can be absent or unsettled during attacks; compression, short sprites and broadcast overlays limit readings.
HP remains a fractional interval. Maximum/integer HP, form and unseen roster are unverified.
Fast moves, modeled energy, stages and switch timing are hypotheses, not screen observations.

| Side | Visible health samples | Missing health samples | Estimated energy samples |
|---|---:|---:|---:|
| mine | 166 | 187 | 54 |
| opponent | 118 | 235 | 0 |

Internal consistency: **fail**.

- shields: they used 1, but 0 charged move(s) were tracked as blocked
- energy: stone_edge at 11.0s had 0 of 55
- ending: no result screen, and the tracker has us on 1 and them on 1
- coverage: clip starts mid-match; initial energy, shields and team history are unknown

Recognition accuracy has not been measured against independent human labels.
The ledger retains unaffected readings during animations. Affected values are pending until fresh evidence resolves them.
Old readings for a fainted Pokemon are historical. Unknown initial values remain unknown.
A final announcement does not fabricate zero HP or a knockout.
