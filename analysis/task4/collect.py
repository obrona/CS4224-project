"""Collect the workload-B optimisation chain (Task 4) into CSV tables.

Run from anywhere:  python3 analysis/task4/collect.py

Experiments: expt_b0 (baseline, for the overview), expt_b7 .. expt_b19 and expt_b26
(expt_b19 under REPEATABLE READ; it ran as expt_b20 and was renumbered), each
with its parent in the chain (PARENT). Every number comes from the experiment's
slurm-results/job-*/benchmark-results/{summary.csv, transaction_metrics.csv,
result-c<N>.txt}; nothing is estimated.

Validity follows analysis/plot_results.py on main: a client count is not valid
when pgbench_exit_code != 0 or at least one client aborted (counted from
result-c<N>.txt).

Output, in analysis/task4/:
  chain_summary.csv       one row per experiment x client count
  chain_overview.csv      one row per experiment: TPS per client count, mean and
                          peak TPS, ratios against its parent and against expt_b0
  chain_transactions.csv  one row per experiment x client count x transaction:
                          tps, latency percentiles, share of total latency and
                          clients inside the transaction (Little's law)
  chain_bottleneck.csv    per experiment and client count, the transaction with
                          the largest latency share
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

# experiment -> (parent in the chain, short label of the change)
CHAIN = {
    "expt_b0": (None, "baseline"),
    "expt_b7": ("expt_b0", "colocate by merchant_id, indexes, fill factors"),
    "expt_b8": ("expt_b7", "distribution-column predicates (T3 join, T5/T8 guards, T1 UPDATE)"),
    "expt_b9": ("expt_b8", "set-based T1"),
    "expt_b10": ("expt_b9", "T7 routed via product_merchant_map"),
    "expt_b11": ("expt_b10", "T5 routed via order_merchant_map"),
    "expt_b12": ("expt_b11", "T6 from merchant_daily_sales rollup"),
    "expt_b13": ("expt_b12", "T1 as delegated function place_order"),
    "expt_b14": ("expt_b13", "8 shards instead of 32"),
    "expt_b15": ("expt_b14", "4 shards (one per worker)"),
    "expt_b16": ("expt_b15", "T7 as delegated function (not carried forward)"),
    "expt_b17": ("expt_b15", "product_merchant_map as reference table"),
    "expt_b18": ("expt_b15", "T7's two lookups merged"),
    "expt_b19": ("expt_b15", "reference table + merged lookup"),
    "expt_b26": ("expt_b19", "REPEATABLE READ instead of SERIALIZABLE (not carried forward)"),
}
TX_NAMES = {"T1": "Place Order", "T2": "Update Inventory", "T3": "Order History",
            "T4": "Product Lookup", "T5": "Update Order Status", "T6": "Global Sales",
            "T7": "Inventory Transfer", "T8": "Update Customer", "T9": "Update Product"}
ABORT = re.compile(r"client \d+ script \d+ aborted in command \d+ query \d+: ERROR:\s+(.*)")


def job_dir(expt):
    jobs = sorted((REPO / expt / "slurm-results").glob("job-*/benchmark-results"))
    if len(jobs) != 1:
        raise RuntimeError(f"{expt}: expected one job-*/benchmark-results, found {len(jobs)}")
    return jobs[0]


def aborts(res_file):
    if not res_file.exists():
        return 0, ""
    msgs = ABORT.findall(res_file.read_text(errors="ignore"))
    kinds = sorted({re.sub(r" for shard \d+.*| to the node \S+.*", "", m).strip() for m in msgs})
    return len(msgs), "; ".join(kinds)


def load():
    summ, tx = [], []
    for expt, (parent, label) in CHAIN.items():
        d = job_dir(expt)
        s = pd.read_csv(d / "summary.csv")
        s.insert(0, "experiment", expt)
        s.insert(1, "change", label)
        s.insert(2, "parent", parent or "")
        s["job"] = d.parent.name
        ab = [aborts(d / f"result-c{c}.txt") for c in s.clients]
        s["aborted_clients"] = [a for a, _ in ab]
        s["abort_errors"] = [e for _, e in ab]
        s["valid"] = (s.pgbench_exit_code == 0) & (s.aborted_clients == 0)
        summ.append(s)
        t = pd.read_csv(d / "transaction_metrics.csv")
        t = t[t.transaction.str.match(r"^T\d$")].copy()
        t.insert(0, "experiment", expt)
        tx.append(t)
    return pd.concat(summ, ignore_index=True), pd.concat(tx, ignore_index=True)


def main():
    S, T = load()
    S.to_csv(OUT / "chain_summary.csv", index=False)

    # Per transaction: share of total measured latency and Little's-law occupancy.
    T["latency_work"] = T.successful_transactions * T.avg_latency_ms
    T["share_pct"] = 100 * T.latency_work / T.groupby(["experiment", "clients"]).latency_work.transform("sum")
    T["clients_inside"] = T.tps * T.avg_latency_ms / 1000.0
    T.drop(columns="latency_work").round(4).to_csv(OUT / "chain_transactions.csv", index=False)

    top = T.loc[T.groupby(["experiment", "clients"]).share_pct.idxmax(),
                ["experiment", "clients", "transaction", "name", "share_pct", "avg_latency_ms",
                 "tps", "clients_inside"]]
    top.round(2).to_csv(OUT / "chain_bottleneck.csv", index=False)

    # Overview: TPS per client count, mean and peak, and step ratios.
    piv = S.pivot(index="experiment", columns="clients", values="overall_tps")
    piv.columns = [f"tps_c{c}" for c in piv.columns]
    ov = piv.copy()
    counts = S.groupby("experiment").clients.apply(list)
    ov["mean_tps"] = piv.mean(axis=1)
    ov["peak_tps"] = piv.max(axis=1)
    ov["peak_clients"] = piv.idxmax(axis=1).str.removeprefix("tps_c").astype(int)
    ov["all_valid"] = S.groupby("experiment").valid.all()
    ov["invalid_counts"] = S[~S.valid].groupby("experiment").clients.apply(
        lambda c: " ".join(f"c{x}" for x in c))
    ov["invalid_counts"] = ov["invalid_counts"].fillna("")
    ov["parent"] = [CHAIN[e][0] or "" for e in ov.index]
    ov["change"] = [CHAIN[e][1] for e in ov.index]
    for col in ("mean_tps", "tps_c1", "tps_c64", "peak_tps"):
        ov[f"{col}_x_parent"] = [ov.loc[e, col] / ov.loc[p, col] if p else np.nan
                                 for e, p in zip(ov.index, ov.parent)]
        ov[f"{col}_x_b0"] = ov[col] / ov.loc["expt_b0", col]
    ov = ov.loc[list(CHAIN)]
    ov.round(3).to_csv(OUT / "chain_overview.csv", index_label="experiment")
    print(f"wrote 4 CSVs to {OUT.relative_to(REPO)} for {len(CHAIN)} experiments "
          f"(client counts per experiment: {sorted(set(map(len, counts)))})")


if __name__ == "__main__":
    main()
