# Early-Entry Simulation with KNN Health Monitor

> [!CAUTION]
> **The table below is SURVIVOR-BIASED and INVALID — do not read the +$60 as an edge.** The population is
> `n_post>4` (trades with a Bar-4 KNN state), which silently EXCLUDES the ~22% quick-failures (n≤4) — exactly the
> losers an early entry eats. On the FULL OOS universe (all flips): flip-close entry **−$20.7/tr** (DD $770K, 31%
> win), Bar1 −$14.2, Bar2 −$6.0, Bar4 +$0.2. So **earlier entry is monotonically WORSE, not better** — the apparent
> +$60 is 100% the survivor filter. Early-flip entry remains DEAD (the coin-flip result). The protected variant
> changes nothing material. (Caught via a full-universe re-check; the state-transition atlas above is unaffected
> — it's a within-active-trade diagnostic.)

Enter at flip-close / Bar1 / Bar2 / Bar4, NO tight stop. NUMBERS BELOW ARE THE n>4 SURVIVOR SUBSET (biased — see caution).

| Entry | mode | avg/tr | 2025 | 2026 | maxDD | p5 trade | n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| flip-close | hold-to-flip | $+60 | $+62 | $+53 | $17,010 | $-508 | 28,191 |
| flip-close | protect@profit+stall | $+61 | $+62 | $+58 | $13,035 | $-472 | 28,191 |
| Bar1 | hold-to-flip | $+60 | $+63 | $+54 | $16,148 | $-508 | 28,191 |
| Bar1 | protect@profit+stall | $+62 | $+63 | $+60 | $12,812 | $-472 | 28,191 |
| Bar2 | hold-to-flip | $+42 | $+46 | $+30 | $18,240 | $-518 | 28,191 |
| Bar2 | protect@profit+stall | $+43 | $+46 | $+33 | $14,725 | $-472 | 28,191 |
| Bar4 | hold-to-flip | $+0 | $+6 | $-16 | $189,308 | $-552 | 28,191 |
| Bar4 | protect@profit+stall | $-0 | $+4 | $-14 | $176,220 | $-518 | 28,191 |