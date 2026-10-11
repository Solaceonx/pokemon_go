# pokemongo · Match 04 · right

Source: https://www.twitch.tv/videos/2897295240
Source interval: 1065.500-1292.500 seconds.
Match: `tw-2897295240-match-004`; view: `right`; dataset: `exposed_regression`.

Read all saved clip time: 3405 samples at 15 Hz, text at 3 Hz; 143 reconstructed model states.
Partial beginning: False; partial ending: False.

Screen evidence includes names/CP, health bars, shields, party markers and visible controls.
Bars can be absent or unsettled during attacks; compression, short sprites and broadcast overlays limit readings.
HP remains a fractional interval. Maximum/integer HP, form and unseen roster are unverified.
Fast moves, modeled energy, stages and switch timing are hypotheses, not screen observations.

| Side | Visible health samples | Missing health samples | Estimated energy samples |
|---|---:|---:|---:|
| mine | 1364 | 2041 | 321 |
| opponent | 1406 | 1999 | 0 |

Internal consistency: **fail**.

- energy: payback at 148.5s had 30 of 60; air_cutter at 164.5s had 20 of 40
- ending: no result screen, and the tracker has us on 1 and them on 2

Recognition accuracy has not been measured against independent human labels.
The ledger retains unaffected readings during animations. Affected values are pending until fresh evidence resolves them.
Old readings for a fainted Pokemon are historical. Unknown initial values remain unknown.
A final announcement does not fabricate zero HP or a knockout.
