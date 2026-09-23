# Runner vs giveback from a common anchor (+1A, +1.5A; +2A for reference)

Every trade here has shown the same progress. Outcomes are split three ways:
- **fail:** never reaches +2A;
- **giveback:** reaches +2A, then the terminal flip exits at or below entry;
- **sustained:** reaches +2A and wins.

## Class shares by speed tercile (speed cutpoints fixed on discovery)

| anchor | block | speed | N | fail | giveback | sustained | giveback share of +2A | median trigger vs entry (A) |
|---|---|---|---|---|---|---|---|---|
| +1A | discovery | fast | 879 | 34.8% | 12.6% | 52.6% | 19.4% | −1.28 |
| | | slow | 893 | 40.9% | 8.5% | 50.6% | 14.4% | −0.69 |
| | replication | fast | 263 | 36.5% | 11.0% | 52.5% | 17.4% | −1.32 |
| | | slow | 295 | 39.7% | 7.5% | 52.9% | 12.4% | −0.69 |
| +1.5A | discovery | fast | 696 | 18.2% | 18.4% | 63.4% | 22.5% | −1.12 |
| | | slow | 704 | 22.3% | 9.7% | 68.0% | 12.4% | −0.32 |
| | replication | fast | 227 | 20.3% | 14.5% | 65.2% | 18.2% | −1.10 |
| | | slow | 234 | 23.5% | 9.8% | 66.7% | 12.8% | −0.31 |

**Fast arrivals have two opposite tendencies.** They are slightly *more* likely to reach +2A (fewer fails).
They are also more likely to give it back. Both tendencies line up with the trigger position: fast
arrivals have the trigger 0.6–0.8A further below entry.

**Class medians at the anchor** (pooled):

| anchor | class | N | time to anchor | ret30 | MAE so far | trigger vs entry |
|---|---|---|---|---|---|---|
| +1A | fail | 1,308 | 167 s | 0.69 | 0.44 | −0.89 |
| | giveback | 373 | **124 s** | **0.81** | 0.43 | **−1.05** |
| | sustained | 1,847 | 150 s | 0.72 | 0.42 | −0.95 |
| +1.5A | fail | 571 | 269 s | 0.69 | 0.48 | −0.63 |
| | giveback | 373 | **191 s** | **0.90** | 0.50 | **−0.86** |
| | sustained | 1,847 | 258 s | 0.74 | 0.46 | −0.68 |

## Can givebacks be told apart before +2A?

**With the mechanics removed, only weakly, and not reproducibly.**

- **At +1A:** nothing meaningful against the engine null. Speed −2.2pp, ret30 +3.2pp, MAE +2.6pp.
- **At +1.5A:** in discovery, ret30 gives +9.1pp and speed −5.6pp against N3. In replication they are +2.8pp
  and −1.2pp.
- **At +2A:** ret30 gives +10.7pp in discovery and +4.8pp in replication.

**What drives giveback is where the trailing flip trigger sits when price turns.** At the +2A touch the
giveback rate is 25.5%, 17.3% and 7.7% from the lowest to the highest trigger tercile. That is a
**causal, observable state variable**, and it is mechanical by construction: it is the exit boundary itself.

Any later management study should treat the trigger position as the baseline, not as a discovery.

Power for giveback is limited: replication has 546 +2A trades, and the minimum detectable tercile difference
is 0.12.

Machine-readable: `artifacts/GIVEBACK_THREE_CLASS.*`, `artifacts/PATH_EFFECTS.*` (outcomes `G_raw` and
`G_res_N3`) and `artifacts/TRIGGER_CONDITIONING.*`.
