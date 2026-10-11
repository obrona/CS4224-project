"""Collect the 2^4 ablation around expt_b20 (expt_b21 .. expt_b37) into CSV tables.

ARCHIVED: those folders were deleted on 2026-10-11 (still in git, commits 41928f59 ..
59822755), so this script no longer runs as is; see ablation/README.md.

Run from anywhere:  python3 analysis/task4/collect_ablation.py

Design: ablation_b20/README.md and manifest.csv. Four factors (T5 routing, T6
rollup, T7 routing, T1 delegation), all-on cell = expt_b20 with replicates
expt_b21 and expt_b22.

Output, in analysis/task4/ablation/:
  cells.csv          one row per cell: factor levels, TPS per client count, mean,
                     retried transactions and serialization failures at 64 clients,
                     and the transaction holding most clients at 64 (Little's law)
  leave_one_out.csv  all-on reference / one-factor-off cell, per client count and mean
  conditional.csv    each factor's on/off TPS ratio for every setting of the other three
  midnight.csv       every client-count run (all experiments) whose measured period
                     falls after the midnight following its data reset

The all-on reference is the mean of the same-night replicates expt_b21 and
expt_b22, except at 64 clients where expt_b22 crossed midnight (see midnight.csv
and the T6 note in README) and expt_b21 alone is used.
"""

import datetime as dt
import re
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import REPO, job_dir  # noqa: E402

OUT = Path(__file__).resolve().parent / "ablation"
CLIENTS = [1, 4, 8, 16, 32, 64]
FACTORS = {"T5": "t5_routing", "T6": "t6_rollup", "T7": "t7_routing", "T1": "t1_delegated"}


def midnight_runs():
    """Runs whose data was generated before a midnight that falls inside the measured run.

    Initial orders are stamped current_timestamp - k days at reset, so T6's
    boundary-day scan is empty unless the run's date is later than the reset's.
    """
    reset_re = re.compile(r"^\[(\S+ \S+)\] Resetting database.*client-count c(\d+)")
    run_re = re.compile(r"^\[(\S+ \S+)\] Measured run: clients=(\d+)")
    rows = []
    for log in sorted(REPO.glob("expt_*/slurm-results/job-*/benchmark.log")):
        reset, run = {}, {}
        for line in log.open(errors="ignore"):
            if m := reset_re.match(line):
                reset[int(m.group(2))] = dt.datetime.fromisoformat(m.group(1))
            if m := run_re.match(line):
                run[int(m.group(2))] = dt.datetime.fromisoformat(m.group(1))
        for c, start in run.items():
            end = start + dt.timedelta(seconds=600)
            if c in reset and end.date() > reset[c].date():
                midnight = dt.datetime.combine(end.date(), dt.time())
                rows.append(dict(experiment=log.parts[-4], clients=c, reset=reset[c], run_start=start,
                                 run_end=end, seconds_after_midnight=(end - max(start, midnight)).seconds))
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(exist_ok=True)
    man = pd.read_csv(REPO / "ablation_b20" / "manifest.csv").set_index("experiment")
    rows = []
    for e in man.index:
        d = job_dir(e)
        s = pd.read_csv(d / "summary.csv").set_index("clients")
        t = pd.read_csv(d / "transaction_metrics.csv")
        t = t[(t.clients == 64) & t.transaction.str.match(r"^T\d$")].set_index("transaction")
        inside = t.tps * t.avg_latency_ms / 1000
        r = dict(experiment=e, **{f: int(man.loc[e, col]) for f, col in FACTORS.items()},
                 off=",".join(f for f, col in FACTORS.items() if man.loc[e, col] == 0) or "-",
                 **{f"tps_c{c}": s.loc[c, "overall_tps"] for c in CLIENTS},
                 retried_c64=s.loc[64, "retried_transactions"],
                 serialization_failures_c64=s.loc[64, "serialization_failures"],
                 top_tx_c64=inside.idxmax(), top_tx_clients_c64=inside.max())
        r["mean_tps"] = np.mean([r[f"tps_c{c}"] for c in CLIENTS])
        rows.append(r)
    cells = pd.DataFrame(rows).set_index("experiment")
    cells.round(2).to_csv(OUT / "cells.csv")

    tps = cells[[f"tps_c{c}" for c in CLIENTS]]
    ref = tps.loc[["expt_b21", "expt_b22"]].mean()
    ref["tps_c64"] = tps.loc["expt_b21", "tps_c64"]
    ref["mean_tps"] = ref.mean()
    full = tps.assign(mean_tps=tps.mean(axis=1))
    full.loc["all-on reference"] = ref

    loo = []
    for f in FACTORS:
        e = next(x for x in man.index if man.loc[x, FACTORS[f]] == 0 and man.loc[x].iloc[:4].sum() == 3)
        loo.append(dict(factor=f, cell=e, **(ref / full.loc[e]).round(3).to_dict()))
    pd.DataFrame(loo).to_csv(OUT / "leave_one_out.csv", index=False)

    def cell(levels):
        if all(levels.values()):
            return "all-on reference"
        return next(x for x in man.index if x not in ("expt_b20", "expt_b21", "expt_b22")
                    and all(man.loc[x, FACTORS[f]] == v for f, v in levels.items()))

    cond = []
    for f in FACTORS:
        others = [g for g in FACTORS if g != f]
        for vals in product([1, 0], repeat=3):
            lv = dict(zip(others, vals))
            on, off = cell({**lv, f: 1}), cell({**lv, f: 0})
            cond.append(dict(factor=f, **{f"{g}_on": v for g, v in lv.items()}, on_cell=on, off_cell=off,
                             ratio_mean=full.loc[on, "mean_tps"] / full.loc[off, "mean_tps"],
                             ratio_c1=full.loc[on, "tps_c1"] / full.loc[off, "tps_c1"],
                             ratio_c64=full.loc[on, "tps_c64"] / full.loc[off, "tps_c64"]))
    pd.DataFrame(cond).round(3).to_csv(OUT / "conditional.csv", index=False)

    midnight_runs().to_csv(OUT / "midnight.csv", index=False)
    print(f"wrote 4 CSVs to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
