import pandas as pd, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def pct(v, t): return 0 if t == 0 else 100 * v / t
def wr(df): return pct((df["pnl"] > 0).sum(), len(df))
def ev(df): return df["pnl"].mean()
def pf(df):
    w = df.loc[df["pnl"] > 0, "pnl"].sum()
    l = abs(df.loc[df["pnl"] < 0, "pnl"].sum())
    return w / l if l > 0 else float("inf")

def classify(r):
    rsn = r.exit_reason
    if rsn == "sl":
        if not r.did_025: return "ImmFail"
        if not r.did_050: return "PartRun"
        if not r.did_100: return "VShape" if r.after_050_revisit_entry else "MidRev"
        return "DeepRev"
    mfe = r.max_mfe_atr
    if mfe < 0.25: return "FlipNeg"
    if mfe < 1.00: return "FlipMod"
    if mfe < 2.00: return "FlipRun"
    return "FlipExp"

LABELS = {"A": "A depth+upclose", "B": "B 5s realign", "C": "C realign+50%"}

print(f"  {'Trigger':<18}  {'n':>6}  {'WR':>6}  {'EV':>8}  {'PF':>5}  {'ImmFail':>8}  {'FlipExp':>8}")
for t, label in LABELS.items():
    df = pd.read_parquet(f"studies/pullback_dna/results/trigger_{t}.parquet")
    df["arch"] = df.apply(classify, axis=1)
    n = len(df)
    imf = (df["arch"] == "ImmFail").sum()
    fex = (df["arch"] == "FlipExp").sum()
    print(f"  {label:<18}  {n:>6,}  {wr(df):>5.1f}%  {ev(df):>+8.1f}"
          f"  {pf(df):>5.2f}  {pct(imf,n):>7.1f}%  {pct(fex,n):>7.1f}%")

for yr in [2025, 2026]:
    print(f"\n  --- {yr} ---")
    for t, label in LABELS.items():
        df = pd.read_parquet(f"studies/pullback_dna/results/trigger_{t}.parquet")
        df["arch"] = df.apply(classify, axis=1)
        df["year"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True).dt.year
        sub = df[df["year"] == yr]; n = len(sub)
        imf = (sub["arch"] == "ImmFail").sum()
        fex = (sub["arch"] == "FlipExp").sum()
        print(f"  {label:<18}  n={n:>5,}  WR={wr(sub):>4.1f}%  EV={ev(sub):>+7.1f}"
              f"  ImmFail={pct(imf,n):>4.1f}%  FlipExp={pct(fex,n):>4.1f}%")
