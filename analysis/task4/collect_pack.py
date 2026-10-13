"""Collect the statistics for the Task 4 evidence pack (workload B, Section 5).

Run from anywhere:  python3 analysis/task4/collect_pack.py

Reads every expt_b* run in the working tree (via collect.py's job_dir) and the
workload-A chain from git (origin/main: expt_a0, expt_a7 .. expt_a15, numbered
like workload B's chain). Writes CSVs to analysis/task4/pack/; README.md there
says which section each one feeds. Nothing is estimated except the columns
marked "pred" (closed-loop predictions: TPS = clients / sum_i w_i * latency_i).

The final design is expt_b19 with replicates expt_b20 and expt_b21; "final" in
every file means those three runs. Standard errors use n = 3 and the 95%
interval uses Student's t with 2 degrees of freedom (4.303).
"""

import importlib.util
import io
import re
import subprocess
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True  # no __pycache__ next to the scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import REPO, aborts, job_dir  # noqa: E402

OUT = Path(__file__).resolve().parent / "pack"
CLIENTS = [1, 4, 8, 16, 32, 64]
TXS = [f"T{i}" for i in range(1, 10)]
FINAL = ["expt_b19", "expt_b20", "expt_b21"]
T_975_2 = 4.303
W_B = {"T1": .10, "T2": .10, "T3": .05, "T4": .05, "T5": .10, "T6": .10, "T7": .30, "T8": .10, "T9": .10}
FACTORS = {"T5": "t5_routing", "T6": "t6_rollup", "T7": "t7_routing", "T1": "t1_delegated"}
# Workload-B chain step and the workload-A step with the same change (origin/main README).
STEPS = [("baseline", "expt_b0", "expt_a0"),
         ("colocate by merchant_id", "expt_b7", "expt_a7"),
         ("merchant_id in T3's join, T1's UPDATE", "expt_b8", "expt_a8"),
         ("set-based T1", "expt_b9", "expt_a9"),
         ("T7 via product_merchant_map", "expt_b10", "expt_a10"),
         ("T5 via order_merchant_map", "expt_b11", "expt_a11"),
         ("T6 from daily rollup", "expt_b12", "expt_a12"),
         ("T1 delegated (place_order)", "expt_b13", "expt_a13"),
         ("8 shards", "expt_b14", "expt_a14"),
         ("4 shards", "expt_b15", "expt_a15")]


# ------------------------------------------------------------------ loading
def load_b(expt):
    d = job_dir(expt)
    s = pd.read_csv(d / "summary.csv").set_index("clients")
    s["aborted"] = [aborts(d / f"result-c{c}.txt")[0] for c in s.index]
    t = pd.read_csv(d / "transaction_metrics.csv")
    t = t[t.transaction.str.match(r"^T\d$")].set_index(["clients", "transaction"])
    return s, t


def git_show(path):
    r = subprocess.run(["git", "-C", str(REPO), "show", f"origin/main:{path}"],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.stdout


ABORT = re.compile(r"client \d+ script \d+ aborted in command \d+ query \d+: ERROR:")


def load_a(expt):
    tree = subprocess.run(["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", "origin/main", f"{expt}/"],
                          capture_output=True, text=True).stdout.split()
    job = sorted({p.split("/")[2] for p in tree if "/slurm-results/job-" in p})[0]
    base = f"{expt}/slurm-results/{job}"
    s = pd.read_csv(io.StringIO(git_show(f"{base}/benchmark-results/summary.csv"))).set_index("clients")
    s["aborted"] = [len(ABORT.findall(git_show(f"{base}/benchmark-results/result-c{c}.txt"))) for c in s.index]
    t = pd.read_csv(io.StringIO(git_show(f"{base}/benchmark-results/transaction_metrics.csv")))
    t = t[t.transaction.str.match(r"^T\d$")].set_index(["clients", "transaction"])
    cfg = git_show(f"{base}/benchmark-results/config.txt")
    w = {k: int(v) for k, v in re.findall(r"^(T\d)_WEIGHT=(\d+)", cfg, re.M)}
    nodes = " ".join(re.findall(r"xcn\w+", git_show(f"{base}/topology.txt")))
    return s, t, w, job, nodes


def valid(s):
    return (s.pgbench_exit_code == 0) & (s.aborted == 0)


def share_inside(t, w=None):
    """Latency share and Little's-law clients inside, per client count and transaction."""
    x = t.copy()
    x["work"] = x.successful_transactions * x.avg_latency_ms
    x["share_pct"] = 100 * x.work / x.groupby(level=0).work.transform("sum")
    x["inside"] = x.tps * x.avg_latency_ms / 1000
    return x


def mean_r(t, c, w=W_B):
    return sum(w[k] * t.loc[(c, k), "avg_latency_ms"] for k in w)


# --------------------------------------------------------------- placement
def explain_nodes(expt, tx):
    f = job_dir(expt).parent / "explain.log"
    if not f.exists():
        return ""
    m = re.search(rf"^=+ {tx}_\S+\n(.*?)(?=^=+ T\d_|\Z)", f.read_text(errors="ignore"), re.M | re.S)
    return " ".join(sorted(set(re.findall(r"Node: host=(\w+)", m.group(1))))) if m else ""


# --------------------------------------------------------------------- main
def main():
    OUT.mkdir(exist_ok=True)
    B = {}
    names = ["expt_b0"] + [f"expt_b{i}" for i in range(7, 47)]
    for e in names:
        B[e] = load_b(e)

    def tps(e):
        return B[e][0].overall_tps

    # 1. Final benchmark: expt_b19..b21.
    F = pd.DataFrame({e: tps(e) for e in FINAL})
    F.loc["mean"] = F.mean()
    fin = pd.DataFrame({
        "b19": F["expt_b19"], "b20": F["expt_b20"], "b21": F["expt_b21"],
        "mean": F.mean(axis=1), "sd": F.std(axis=1, ddof=1)})
    fin["se"] = fin.sd / np.sqrt(3)
    fin["ci95_lo"] = fin["mean"] - T_975_2 * fin.se
    fin["ci95_hi"] = fin["mean"] + T_975_2 * fin.se
    fin["cv_pct"] = 100 * fin.sd / fin["mean"]
    fin["range_pct"] = 100 * (F.max(axis=1) / F.min(axis=1) - 1)
    extra = {}
    for col in ("overall_avg_latency_ms", "overall_p95_latency_ms", "overall_p99_latency_ms",
                "retried_transactions", "total_retries", "serialization_failures"):
        v = pd.DataFrame({e: B[e][0][col] for e in FINAL})
        extra[f"{col}_mean"] = v.mean(axis=1)
        extra[f"{col}_se"] = v.std(axis=1, ddof=1) / np.sqrt(3)
    fin = fin.join(pd.DataFrame(extra))
    fin.index.name = "clients"
    fin.round(3).to_csv(OUT / "final_benchmark.csv")
    ref = fin["mean"]          # per client count and "mean" (mean TPS over the six counts)
    ref_se = fin["se"]

    rows = []
    for c in CLIENTS:
        for k in TXS:
            v = np.array([share_inside(B[e][1]).loc[(c, k), ["avg_latency_ms", "p95_latency_ms", "p99_latency_ms",
                                                              "share_pct", "inside", "tps"]].values for e in FINAL],
                         dtype=float)
            m, se = v.mean(axis=0), v.std(axis=0, ddof=1) / np.sqrt(3)
            rows.append(dict(clients=c, transaction=k, avg_ms=m[0], avg_se=se[0], p95_ms=m[1], p99_ms=m[2],
                             share_pct=m[3], clients_inside=m[4], tps=m[5]))
    pd.DataFrame(rows).round(3).to_csv(OUT / "final_tx.csv", index=False)

    def vs_final(e):
        x = tps(e)
        out = {f"c{c}": x[c] for c in CLIENTS}
        out["mean"] = x.mean()
        for c in CLIENTS + ["mean"]:
            v = out["mean"] if c == "mean" else x[c]
            key = "mean" if c == "mean" else c
            out[f"ratio_{'mean' if c == 'mean' else f'c{c}'}"] = v / ref[key]
            out[f"z_{'mean' if c == 'mean' else f'c{c}'}"] = (v - ref[key]) / ref_se[key]
        s = B[e][0]
        out["invalid"] = " ".join(f"c{c}({s.loc[c, 'aborted']})" for c in CLIENTS if not valid(s).loc[c])
        out["retried_c64"] = s.loc[64, "retried_transactions"]
        out["serialization_failures_c64"] = s.loc[64, "serialization_failures"]
        return out

    def decomposition(e, refs, c):
        """Weight x latency change of each transaction against the mean of `refs`."""
        lat = {k: np.mean([B[r][1].loc[(c, k), "avg_latency_ms"] for r in refs]) for k in TXS}
        d = {k: W_B[k] * (B[e][1].loc[(c, k), "avg_latency_ms"] - lat[k]) for k in TXS}
        r0 = sum(W_B[k] * lat[k] for k in TXS)
        return d, r0

    # 2. Workload A vs B chain.
    A = {}
    rows = []
    for label, b, a in STEPS:
        sa, ta, wa, job, nodes = load_a(a)
        A[a] = (sa, ta)
        sb, tb = B[b]
        ib, ia = share_inside(tb), share_inside(ta)
        topb = ib.loc[64].share_pct.idxmax()
        topa = ia.loc[64].share_pct.idxmax()
        rows.append(dict(step=label, b_expt=b, a_expt=a,
                         b_mean_tps=sb.overall_tps.mean(), a_mean_tps=sa.overall_tps.mean(),
                         b_c1=sb.loc[1, "overall_tps"], a_c1=sa.loc[1, "overall_tps"],
                         b_c64=sb.loc[64, "overall_tps"], a_c64=sa.loc[64, "overall_tps"],
                         b_top_c64=topb, b_top_share=ib.loc[(64, topb), "share_pct"],
                         a_top_c64=topa, a_top_share=ia.loc[(64, topa), "share_pct"],
                         b_invalid=" ".join(f"c{c}" for c in CLIENTS if not valid(sb).loc[c]),
                         a_invalid=" ".join(f"c{c}({sa.loc[c, 'aborted']})" for c in CLIENTS if not valid(sa).loc[c]),
                         a_job=job, a_nodes=nodes))
    ab = pd.DataFrame(rows)
    for col in ("mean_tps", "c64"):
        for side in "ab":
            ab[f"{side}_{col}_x_step"] = ab[f"{side}_{col}"] / ab[f"{side}_{col}"].shift()
            ab[f"{side}_{col}_x_base"] = ab[f"{side}_{col}"] / ab[f"{side}_{col}"].iloc[0]
    ab.round(3).to_csv(OUT / "a_vs_b_chain.csv", index=False)
    wa = load_a("expt_a0")[2]
    pd.DataFrame({"workload_A": pd.Series(wa) / 100, "workload_B": pd.Series(W_B)}).to_csv(OUT / "mix.csv",
                                                                                          index_label="transaction")
    # Per-transaction latency at 1 client in both workloads' final chain step.
    lat = pd.DataFrame({"b15": B["expt_b15"][1].loc[1].avg_latency_ms, "a15": A["expt_a15"][1].loc[1].avg_latency_ms})
    lat["w_A"] = pd.Series(wa) / 100
    lat["w_B"] = pd.Series(W_B)
    lat["A_weighted_ms"] = lat.w_A * lat.a15
    lat["B_weighted_ms"] = lat.w_B * lat.b15
    lat.round(3).to_csv(OUT / "a_vs_b_latency_c1.csv", index_label="transaction")

    # 3. Everything after b15 against the final benchmark.
    after = [f"expt_b{i}" for i in range(15, 47)]
    pd.DataFrame({e: vs_final(e) for e in after}).T.round(4).to_csv(OUT / "vs_final.csv", index_label="experiment")

    # Closed-loop decompositions: partitions and REPEATABLE READ against the final design,
    # and the partition cells against the ablation cell with the same T1.
    comps = [(e, FINAL, "final") for e in ("expt_b22", "expt_b23", "expt_b24", "expt_b25", "expt_b26")] + \
            [("expt_b22", ["expt_b30"], "b30"), ("expt_b24", ["expt_b30"], "b30"),
             ("expt_b25", ["expt_b30"], "b30"), ("expt_b23", ["expt_b27"], "b27")]
    rows = []
    for e, refs, rname in comps:
        for c in CLIENTS:
            d, r0 = decomposition(e, refs, c)
            meas = tps(e)[c] / np.mean([tps(r)[c] for r in refs])
            rows.append(dict(experiment=e, reference=rname, clients=c, R_ref_ms=r0, **d, total=sum(d.values()),
                             pred_ratio=r0 / (r0 + sum(d.values())), measured_ratio=meas))
    pd.DataFrame(rows).round(4).to_csv(OUT / "decomposition.csv", index=False)

    # Placement of the catalog and orders (workers named in the plans).
    rows = []
    for e in ["expt_b19", "expt_b22", "expt_b23", "expt_b24", "expt_b25", "expt_b42", "expt_b43", "expt_b44",
              "expt_b45", "expt_b46"]:
        rows.append(dict(experiment=e, **{tx: explain_nodes(e, tx) for tx in ("T1", "T3", "T4", "T5", "T6", "T7")}))
    pd.DataFrame(rows).to_csv(OUT / "plan_nodes.csv", index=False)

    # 4. Ablation grid.
    man = pd.read_csv(REPO / "ablation_b19" / "manifest.csv").set_index("experiment")
    grid = man[(man.shard_count == 4) & ~man.index.isin(["expt_b20", "expt_b21"])]

    def cell(levels):
        if all(levels.values()):
            return "final"
        return next(x for x in grid.index if x != "expt_b19"
                    and all(grid.loc[x, FACTORS[f]] == v for f, v in levels.items()))

    def cell_tps(name, c):
        return ref[c] if name == "final" else (tps(name).mean() if c == "mean" else tps(name)[c])

    def cell_valid(name):
        return True if name == "final" else bool(valid(B[name][0]).all())

    rows = []
    for t5, t1, t6, t7 in product([1, 0], repeat=4):
        lv = {"T5": t5, "T6": t6, "T7": t7, "T1": t1}
        nm = cell(lv)
        ins = share_inside(B["expt_b19" if nm == "final" else nm][1]).loc[64].inside
        r = dict(cell=nm, **{f"{k}_on": v for k, v in lv.items()},
                 off=",".join(k for k in ("T5", "T6", "T7", "T1") if not lv[k]) or "-",
                 valid=cell_valid(nm),
                 invalid="" if nm == "final" else vs_final(nm)["invalid"],
                 top_tx_c64=ins.idxmax(), top_tx_clients_c64=ins.max())
        for c in CLIENTS + ["mean"]:
            key = "mean" if c == "mean" else f"c{c}"
            r[f"tps_{key}"] = cell_tps(nm, c)
            r[f"ratio_{key}"] = cell_tps(nm, c) / ref[c]
        rows.append(r)
    cells = pd.DataFrame(rows)
    cells.round(4).to_csv(OUT / "ablation_cells.csv", index=False)

    chain_step = {"T7": ("expt_b10", "expt_b9"), "T5": ("expt_b11", "expt_b10"),
                  "T6": ("expt_b12", "expt_b11"), "T1": ("expt_b13", "expt_b12")}
    a_step = {"T7": ("expt_a10", "expt_a9"), "T5": ("expt_a11", "expt_a10"),
              "T6": ("expt_a12", "expt_a11"), "T1": ("expt_a13", "expt_a12")}
    rr = pd.read_csv(OUT.parent / "ablation" / "leave_one_out.csv").set_index("factor")
    rows = []
    for f in ("T7", "T6", "T1", "T5"):
        nm = cell({**{k: 1 for k in FACTORS}, f: 0})
        rows.append(dict(factor=f, cell=nm,
                         loo_mean=ref["mean"] / tps(nm).mean(), loo_c1=ref[1] / tps(nm)[1],
                         loo_c64=ref[64] / tps(nm)[64],
                         chain_step_B=tps(chain_step[f][0]).mean() / tps(chain_step[f][1]).mean(),
                         chain_step_A=A[a_step[f][0]][0].overall_tps.mean() / A[a_step[f][1]][0].overall_tps.mean(),
                         loo_mean_repeatable_read=rr.loc[f, "mean_tps"], cell_valid=cell_valid(nm)))
    pd.DataFrame(rows).round(3).to_csv(OUT / "ablation_loo.csv", index=False)

    rows = []
    for f in FACTORS:
        others = [g for g in FACTORS if g != f]
        for vals in product([1, 0], repeat=3):
            lv = dict(zip(others, vals))
            on, off = cell({**lv, f: 1}), cell({**lv, f: 0})
            rows.append(dict(factor=f, others_on=",".join(g for g, v in lv.items() if v) or "none",
                             on_cell=on, off_cell=off, both_valid=cell_valid(on) and cell_valid(off),
                             ratio_mean=cell_tps(on, "mean") / cell_tps(off, "mean"),
                             ratio_c1=cell_tps(on, 1) / cell_tps(off, 1),
                             ratio_c64=cell_tps(on, 64) / cell_tps(off, 64)))
    pd.DataFrame(rows).round(3).to_csv(OUT / "ablation_conditional.csv", index=False)

    # 5. Shard sweep (4 shards = the final design).
    sh = {1: "expt_b42", 2: "expt_b43", 4: "final", 8: "expt_b44", 16: "expt_b45", 32: "expt_b46"}
    rows = []
    for n, e in sh.items():
        if e == "final":
            x = {c: ref[c] for c in CLIENTS}
            t6 = {c: np.mean([B[r][1].loc[(c, "T6"), "avg_latency_ms"] for r in FINAL]) for c in (1, 64)}
            t1 = np.mean([B[r][1].loc[(1, "T1"), "avg_latency_ms"] for r in FINAL])
            t7 = np.mean([B[r][1].loc[(1, "T7"), "avg_latency_ms"] for r in FINAL])
            ins = np.mean([share_inside(B[r][1]).loc[(64, "T6"), "inside"] for r in FINAL])
            se = {c: ref_se[c] for c in CLIENTS}
        else:
            x = tps(e).to_dict()
            t = B[e][1]
            t6 = {c: t.loc[(c, "T6"), "avg_latency_ms"] for c in (1, 64)}
            t1, t7 = t.loc[(1, "T1"), "avg_latency_ms"], t.loc[(1, "T7"), "avg_latency_ms"]
            ins = share_inside(t).loc[(64, "T6"), "inside"]
            se = {c: np.nan for c in CLIENTS}
        r = dict(shards=n, experiment=e, **{f"tps_c{c}": x[c] for c in CLIENTS},
                 **{f"se_c{c}": se[c] for c in CLIENTS}, mean_tps=np.mean([x[c] for c in CLIENTS]),
                 peak_tps=max(x.values()), peak_clients=max(x, key=x.get),
                 t6_c1_ms=t6[1], t6_c64_ms=t6[64], t6_clients_inside_c64=ins, t1_c1_ms=t1, t7_c1_ms=t7)
        rows.append(r)
    shards = pd.DataFrame(rows)
    for c in CLIENTS:
        shards[f"ratio_c{c}"] = shards[f"tps_c{c}"] / ref[c]
    shards["ratio_mean"] = shards.mean_tps / ref["mean"]
    shards.round(3).to_csv(OUT / "shards.csv", index=False)
    # The earlier sweeps, before T7 used the reference table (B) and on workload A.
    rows = []
    for n, b, a in ((32, "expt_b13", "expt_a13"), (8, "expt_b14", "expt_a14"), (4, "expt_b15", "expt_a15")):
        rows.append(dict(shards=n, b_expt=b, b_mean=tps(b).mean(), b_c64=tps(b)[64],
                         a_expt=a, a_mean=A[a][0].overall_tps.mean(), a_c64=A[a][0].overall_tps[64]))
    pd.DataFrame(rows).round(2).to_csv(OUT / "shards_earlier.csv", index=False)

    # 6. Validity of every run from b19 on.
    rows = []
    for e in [f"expt_b{i}" for i in range(19, 47)]:
        s = B[e][0]
        for c in CLIENTS:
            if not valid(s).loc[c]:
                rows.append(dict(experiment=e, clients=c, aborted=s.loc[c, "aborted"],
                                 exit_code=s.loc[c, "pgbench_exit_code"]))
    pd.DataFrame(rows).to_csv(OUT / "invalid_points.csv", index=False)

    # Runs reset before midnight and measured after it (T6's boundary-day scan grows).
    spec = importlib.util.spec_from_file_location("collect_ablation", OUT.parent / "collect_ablation.py")
    ca = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ca)
    ca.midnight_runs().to_csv(OUT / "midnight_runs.csv", index=False)
    print(f"wrote {len(list(OUT.glob('*.csv')))} CSVs to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
