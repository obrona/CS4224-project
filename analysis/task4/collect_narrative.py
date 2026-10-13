"""Figure data for the workload-B narrative of Section 5 (Task 4).

Run from anywhere:  python3 analysis/task4/collect_narrative.py

Builds on collect.py (same experiments, same parent chain) and adds what the
chain CSVs do not have: data shaped for figures, the raw pgbench logs (time
series, within-run noise, retries per transaction, latency percentiles), the
T7 plans from explain.log, and the placement of merchants on workers computed
from Citus's hash function. Nothing is estimated except where a column says
"pred" (a closed-loop prediction, defined in narrative/README.md).

Output, in analysis/task4/narrative/ (one CSV per figure or table; README.md
there says which figure each one feeds):
  latency_by_tx.csv          avg latency per transaction at 1 and 64 clients
  clients_inside_c64.csv     Little's-law clients inside each transaction, 64 clients
  latency_share.csv          share of latency per transaction, 1 and 64 clients
  tx_by_clients.csv          per transaction: avg latency and TPS at every client count
  t7_latency.csv             T7 avg/p50/p95/p99 at every client count
  t7_cdf.csv                 T7 latency percentiles (0.5 .. 99.9) at 1 and 64 clients
  response_time_delta.csv    per comparison and transaction: weight x change in avg latency
  step_prediction.csv        measured TPS ratio against closed-loop predictions
  rel_tps.csv                TPS relative to a reference experiment, with batch-means CI
  noise_batch_means.csv      TPS from the logs in ten 60 s windows: mean, sd, 95% CI
  tps_timeseries_10s.csv     TPS in 10 s windows over the measured run
  retries_by_tx.csv          retried and failed transactions per transaction type
  closed_loop_check.csv      N against X * R (Little's law for the whole system)
  t7_plans.csv               T7 statements in explain.log: tasks, nodes, timings
  placement.csv              merchants, hot merchants and P(T7 crosses workers) per shard count
"""

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True  # no __pycache__ next to the scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import CHAIN, REPO, TX_NAMES, job_dir  # noqa: E402

OUT = Path(__file__).resolve().parent / "narrative"
CLIENTS = [1, 4, 8, 16, 32, 64]
TXS = [f"T{i}" for i in range(1, 10)]
WINDOW_S = 600                      # measured run length (DURATION)
BATCHES = 10                        # batch means: ten 60 s windows
T_975_9 = 2.262                     # Student t, 97.5%, 9 degrees of freedom
CDF_PCTS = np.r_[np.arange(0.5, 100, 0.5), 99.9]


def short(expt):
    return expt.removeprefix("expt_")


def weights(expt):
    """Transaction weights from the run's config.txt, as fractions."""
    cfg = (job_dir(expt) / "config.txt").read_text()
    w = {t: int(re.search(rf"^{t}_WEIGHT=(\d+)", cfg, re.M).group(1)) for t in TXS}
    total = sum(w.values())
    return {t: v / total for t, v in w.items()}


def read_log(expt, clients):
    """The combined pgbench log: one row per transaction (failed ones included)."""
    f = job_dir(expt) / "logs" / f"transactions-c{clients}.log"
    df = pd.read_csv(f, sep=" ", header=None, usecols=[2, 3, 4, 5, 6],
                     names=["lat", "script", "sec", "usec", "retries"],
                     dtype={"lat": str, "script": np.int8, "sec": np.int64,
                            "usec": np.int64, "retries": np.int16})
    df["ok"] = df.lat.str.isdigit()
    df["lat_us"] = pd.to_numeric(df.lat.where(df.ok), errors="coerce")
    df["t"] = df.sec + df.usec / 1e6
    df["tx"] = "T" + (df.script.astype(int) + 1).astype(str)
    return df.drop(columns=["lat", "sec", "usec"])


# --------------------------------------------------------------------- logs
def from_logs():
    """One pass over every log: batch means, time series, retries, T7 samples."""
    noise, series, retries, t7 = [], [], [], {}
    for expt in CHAIN:
        for c in CLIENTS:
            df = read_log(expt, c)
            ok = df[df.ok]
            t0 = df.t.min()
            # Ten 60 s batches; a record stamped exactly at t0 + 600 s joins the last.
            b = np.minimum(((ok.t - t0) // (WINDOW_S / BATCHES)).astype(int), BATCHES - 1)
            per = ok.groupby(b).size().reindex(range(BATCHES), fill_value=0) / (WINDOW_S / BATCHES)
            noise.append(dict(experiment=expt, clients=c, tps_log=len(ok) / WINDOW_S,
                              batch_mean=per.mean(), batch_sd=per.std(ddof=1),
                              ci95=T_975_9 * per.std(ddof=1) / np.sqrt(BATCHES),
                              batch_min=per.min(), batch_max=per.max()))
            w = np.minimum(((ok.t - t0) // 10).astype(int), WINDOW_S // 10 - 1)
            ts = ok.groupby(w).size().reindex(range(WINDOW_S // 10), fill_value=0) / 10
            series += [dict(experiment=expt, clients=c, t_start_s=10 * i, tps=v)
                       for i, v in ts.items()]
            g = df.groupby("tx")
            r = pd.DataFrame({
                "successful": g.ok.sum(),
                "failed": g.ok.size() - g.ok.sum(),
                "retried_tx": g.retries.apply(lambda s: (s > 0).sum()),
                "total_retries": g.retries.sum(),
            }).reindex(TXS, fill_value=0)
            r["retried_pct"] = 100 * r.retried_tx / (r.successful + r.failed)
            r.insert(0, "clients", c)
            r.insert(0, "experiment", expt)
            retries.append(r.reset_index(names="transaction"))
            if c in (1, 64):
                t7[(expt, c)] = ok.loc[ok.tx == "T7", "lat_us"].to_numpy() / 1000.0
            print(f"  {expt} c{c}: {len(df):,} records", flush=True)
    return (pd.DataFrame(noise), pd.DataFrame(series),
            pd.concat(retries, ignore_index=True), t7)


# ------------------------------------------------------------------ explain
EXPLAIN_BLOCK = re.compile(r"^EXPLAIN \((?P<opts>[^)]*)\)\n(?P<body>.*?)(?=^EXPLAIN \(|^ROLLBACK|^RESET|\Z)",
                           re.M | re.S)


def t7_plans():
    rows = []
    for expt in CHAIN:
        f = job_dir(expt).parent / "explain.log"
        if not f.exists():
            continue
        text = f.read_text(errors="ignore")
        m = re.search(r"^=+ T7_\S+\n(.*?)(?=^=+ T8_|\Z)", text, re.M | re.S)
        if not m:
            continue
        for blk in EXPLAIN_BLOCK.finditer(m.group(1)):
            body = blk.group("body")
            if "transfer_inventory" in body:
                kind = "delegated call"
            elif "product_merchant_map" in body:
                kind = "merged lookup" if "FILTER" in body else "lookup"
            elif "debit" in body:
                kind = "debit"
            elif "credit" in body:
                kind = "credit"
            else:
                kind = "other"
            tasks = re.search(r"Task Count: (\d+)", body)
            coord = re.findall(r"^Execution Time: ([\d.]+) ms", body, re.M)
            worker = re.findall(r"^\s+Execution Time: ([\d.]+) ms", body, re.M)
            rows.append(dict(
                experiment=expt, statement=kind, analyze="ANALYZE" in blk.group("opts"),
                task_count=int(tasks.group(1)) if tasks else np.nan,
                nodes=" ".join(sorted(set(re.findall(r"Node: host=(\S+)", body)))),
                coordinator_exec_ms=float(coord[-1]) if coord else np.nan,
                worker_exec_ms=" ".join(worker)))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- placement
# Citus places a bigint distribution value by PostgreSQL's hashint8, splits the
# int32 hash range into equal shard intervals, and assigns shard i to worker
# i mod 4. Checked against explain.log: merchants 1 and 2 land on shard
# indexes (0, 3) with 4 shards, (0, 6) with 8 and (1, 24) with 32, on the
# workers the plans name.
M32 = 0xFFFFFFFF


def _rot(x, k):
    return ((x << k) | (x >> (32 - k))) & M32


def _hash_uint32(k):
    a = b = c = (0x9E3779B9 + 4 + 3923095) & M32
    a = (a + k) & M32
    c ^= b; c = (c - _rot(b, 14)) & M32
    a ^= c; a = (a - _rot(c, 11)) & M32
    b ^= a; b = (b - _rot(a, 25)) & M32
    c ^= b; c = (c - _rot(b, 16)) & M32
    a ^= c; a = (a - _rot(c, 4)) & M32
    b ^= a; b = (b - _rot(a, 14)) & M32
    c ^= b; c = (c - _rot(b, 24)) & M32
    return c


def hashint8(v):
    lo, hi = v & M32, (v >> 32) & M32
    lo ^= hi if v >= 0 else (~hi & M32)
    h = _hash_uint32(lo)
    return h - (1 << 32) if h >= (1 << 31) else h


def shard_index(v, shards):
    return min((hashint8(v) + (1 << 31)) // ((1 << 32) // shards), shards - 1)


def placement(num_merchants=1000, hot=100, num_products=500_000, workers=4):
    rows = []
    for shards in (32, 8, 4):
        worker = np.array([shard_index(m, shards) % workers for m in range(1, num_merchants + 1)])
        # Product p belongs to merchant 1 + (p - 1) % NUM_MERCHANTS (data generator).
        merchant_of = 1 + (np.arange(1, num_products + 1) - 1) % num_merchants
        prod_share = np.bincount(worker[merchant_of - 1], minlength=workers) / num_products
        row = dict(shards=shards, p_t7_cross_worker=1 - (prod_share ** 2).sum(),
                   p_t7_same_merchant=1 / num_merchants)
        for k in range(workers):
            row[f"merchants_w{k + 1}"] = int((worker == k).sum())
            row[f"hot_merchants_w{k + 1}"] = int((worker[:hot] == k).sum())
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------- main
def main():
    OUT.mkdir(exist_ok=True)
    S = pd.read_csv(OUT.parent / "chain_summary.csv")
    T = pd.read_csv(OUT.parent / "chain_transactions.csv")
    W = weights("expt_b0")
    assert all(weights(e) == W for e in CHAIN), "transaction weights differ between runs"
    T["weight"] = T.transaction.map(W)

    def wide(df, value, cols, index="transaction"):
        p = df.pivot_table(index=index, columns=cols, values=value)
        p.columns = ["_".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in p.columns]
        return p

    # Latency per transaction at 1 and 64 clients, one column per experiment.
    L = T[T.clients.isin([1, 64])].assign(col=lambda d: d.experiment.map(short) + "_c" + d.clients.astype(str))
    lat = wide(L, "avg_latency_ms", "col")
    lat = lat[[f"{short(e)}_c{c}" for c in (1, 64) for e in CHAIN]]
    lat.insert(0, "name", [TX_NAMES[t] for t in lat.index])
    lat.insert(1, "weight", [W[t] for t in lat.index])
    lat.round(3).to_csv(OUT / "latency_by_tx.csv")

    # Clients inside each transaction at 64 clients (stacked bars), and shares.
    ci = T[T.clients == 64].pivot(index="experiment", columns="transaction", values="clients_inside")
    ci = ci.loc[list(CHAIN)]
    ci["total"] = ci.sum(axis=1)
    ci.index = ci.index.map(short)
    ci.round(2).to_csv(OUT / "clients_inside_c64.csv")
    sh = T[T.clients.isin([1, 64])].pivot_table(index=["experiment", "clients"],
                                                 columns="transaction", values="share_pct")
    sh = sh.reindex([(e, c) for e in CHAIN for c in (1, 64)])
    sh.round(2).to_csv(OUT / "latency_share.csv")

    # Every transaction at every client count: avg latency and TPS.
    tb = T.pivot_table(index=["transaction", "clients"], columns="experiment",
                       values=["avg_latency_ms", "tps"])
    tb.columns = [f"{short(e)}_{'lat' if v == 'avg_latency_ms' else 'tps'}" for v, e in tb.columns]
    order = [f"{short(e)}_{k}" for k in ("lat", "tps") for e in CHAIN]
    tb[order].round(3).to_csv(OUT / "tx_by_clients.csv")

    # T7 percentiles from transaction_metrics.csv.
    t7 = T[T.transaction == "T7"][["experiment", "clients", "tps", "avg_latency_ms",
                                   "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "share_pct",
                                   "clients_inside"]]
    t7.round(3).to_csv(OUT / "t7_latency.csv", index=False)

    # Closed-loop view: with no think time, X = N / R, where R is the mean
    # response time per transaction. R_mix = sum_i w_i * avg_latency_i.
    R = (T.weight * T.avg_latency_ms).groupby([T.experiment, T.clients]).sum().rename("R_mix_ms")
    cl = S.set_index(["experiment", "clients"])[["overall_tps", "overall_avg_latency_ms"]].join(R)
    cl["X_times_R_overall"] = cl.overall_tps * cl.overall_avg_latency_ms / 1000
    cl["X_times_R_mix"] = cl.overall_tps * cl.R_mix_ms / 1000
    cl.round(3).to_csv(OUT / "closed_loop_check.csv")

    # Response-time decomposition of each step: w_i * (child - parent) latency.
    comparisons = [(e, p) for e, (p, _) in CHAIN.items() if p] + [("expt_b26", "expt_b15")]
    lt = T.set_index(["experiment", "clients", "transaction"]).avg_latency_ms
    rows, preds = [], []
    for child, parent in comparisons:
        for c in CLIENTS:
            d = {t: W[t] * (lt[child, c, t] - lt[parent, c, t]) for t in TXS}
            rows.append(dict(comparison=f"{short(child)} vs {short(parent)}", clients=c, **d,
                             total=sum(d.values())))
            Rp, Rc = R[parent, c], R[child, c]
            Xp, Xc = cl.overall_tps[parent, c], cl.overall_tps[child, c]
            preds.append(dict(
                comparison=f"{short(child)} vs {short(parent)}", clients=c,
                measured=Xc / Xp,
                pred_all_tx=Rp / Rc,
                pred_t7_only=Rp / (Rp + d["T7"]),
                t7_share_parent=W["T7"] * lt[parent, c, "T7"] / Rp,
                t7_latency_change=lt[child, c, "T7"] / lt[parent, c, "T7"] - 1))
    pd.DataFrame(rows).round(4).to_csv(OUT / "response_time_delta.csv", index=False)
    pd.DataFrame(preds).round(4).to_csv(OUT / "step_prediction.csv", index=False)

    # Raw logs.
    print("reading pgbench logs ...")
    noise, series, retries, t7s = from_logs()
    noise = noise.merge(S[["experiment", "clients", "overall_tps"]], on=["experiment", "clients"])
    noise["ci95_pct"] = 100 * noise.ci95 / noise.batch_mean
    noise.round(3).to_csv(OUT / "noise_batch_means.csv", index=False)
    series.round(2).to_csv(OUT / "tps_timeseries_10s.csv", index=False)
    retries.round(4).to_csv(OUT / "retries_by_tx.csv", index=False)

    cdf = {"pct": CDF_PCTS}
    for (e, c), v in t7s.items():
        cdf[f"{short(e)}_c{c}"] = np.percentile(v, CDF_PCTS)
    pd.DataFrame(cdf).round(3).to_csv(OUT / "t7_cdf.csv", index=False)

    # T7 histogram at 1 client (fraction of calls per 0.25 ms bin). The
    # delegated T7 of expt_b16 is bimodal: fast when the credit is local.
    edges = np.arange(0, 16.25, 0.25)
    hist = {"bin_lo_ms": edges[:-1]}
    for e in ("expt_b15", "expt_b16", "expt_b17", "expt_b18", "expt_b19"):
        v = t7s[(e, 1)]
        hist[short(e)] = np.histogram(v, bins=edges)[0] / len(v)
    pd.DataFrame(hist).round(5).to_csv(OUT / "t7_hist_c1.csv", index=False)

    # Relative TPS with a batch-means CI on the ratio (delta method, within-run
    # noise only: it says nothing about run-to-run variation).
    nz = noise.set_index(["experiment", "clients"])
    rel = []
    for child, ref in [(f"expt_b{i}", "expt_b15") for i in (16, 17, 18, 19, 26)] + \
                      [("expt_b26", "expt_b19"), ("expt_b10", "expt_b9"), ("expt_b8", "expt_b7")]:
        for c in CLIENTS:
            a, b = nz.loc[(child, c)], nz.loc[(ref, c)]
            ratio = a.overall_tps / b.overall_tps
            half = ratio * np.hypot(a.ci95 / a.batch_mean, b.ci95 / b.batch_mean)
            rel.append(dict(experiment=short(child), reference=short(ref), clients=c,
                            ratio=ratio, ci95_lo=ratio - half, ci95_hi=ratio + half))
    pd.DataFrame(rel).round(4).to_csv(OUT / "rel_tps.csv", index=False)

    t7_plans().to_csv(OUT / "t7_plans.csv", index=False)
    placement().round(4).to_csv(OUT / "placement.csv", index=False)
    print(f"wrote {len(list(OUT.glob('*.csv')))} CSVs to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
