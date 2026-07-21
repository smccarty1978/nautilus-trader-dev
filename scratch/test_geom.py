import random, math, time
import numpy as np

def run_step_by_step(n_bars, p, seed):
    rng = random.Random(seed)
    j = 0
    entries = []
    while j < n_bars:
        if rng.random() < p:
            entries.append(j)
            j += 10 # dummy hold duration
        else:
            j += 1
    return entries

def run_geom_skip(n_bars, p, seed):
    rng = random.Random(seed)
    j = 0
    entries = []
    log_1_p = math.log(1.0 - p)
    while j < n_bars:
        u = rng.random()
        if u == 0.0:
            u = 1e-15
        skip = int(math.floor(math.log(u) / log_1_p))
        j += skip
        if j >= n_bars:
            break
        entries.append(j)
        j += 10 # dummy hold duration
    return entries

# Test equivalence of statistics
p = 0.025
n_bars = 350000
seeds = range(100)

t0 = time.time()
counts_step = [len(run_step_by_step(n_bars, p, s)) for s in seeds]
t1 = time.time()
print(f"Step-by-step: mean count = {np.mean(counts_step):.2f}, std = {np.std(counts_step):.2f}, time = {t1-t0:.4f}s")

t0 = time.time()
counts_geom = [len(run_geom_skip(n_bars, p, s)) for s in seeds]
t2 = time.time()
print(f"Geometric skip: mean count = {np.mean(counts_geom):.2f}, std = {np.std(counts_geom):.2f}, time = {t2-t0:.4f}s")
