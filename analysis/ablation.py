"""Analyse one workload's ablation: a 2^4 x 2 factorial (expt_<s>300 .. expt_<s>331).

Run from anywhere:  python3 analysis/ablation.py [--side a|b]     (default a)

The side s is the workload, a or b; the two grids are analysed separately, never
together (they run on disjoint node sets). Cells and factor levels come only from
the side's manifest, ablation/manifest.csv (a) or ablation/manifest_b.csv (b).
Five binary factors
  T5R  t5_routing     T6R  t6_rollup     T7R  t7_routing     SH8  shards8
  DEL  t1_mode: set (OFF) or fn (ON, place_order delegated to a function)
Cell expt_<s><300 + 16*m + mask>, m = 0/1 for set/fn, mask bits T5R=1, T6R=2,
T7R=4, SH8=8; any manifest source other than "replicate of ..." (generated,
existing, renamed from ...) is a grid cell. Replicates expt_<s><index>_<k>
("replicate of expt_<s><index>", k >= 1) are a further run of cell
expt_<s><index> with the same code; they are reported separately
(replicate_check), each against its cell, and are not part of the 32-cell fit.

Each cell is loaded with plot_results.load_experiment, so its cross-checks and its
validity rule (pgbench exit code 0 and no aborted client) are the ones used
everywhere else. A cell has not been run yet when its directory or its
slurm-results/ is absent, when its one job-*/ has no benchmark-results/ yet (the
job is setting up, or died before the benchmark: the job id is reported), when
its job has not finished a single client count
(summary.csv holds only its header), or when it lacks a client count that other
cells have (partial: still running). Nothing is imputed.

Responses, per cell, valid points only:
  R_peak  highest TPS over the client counts (and at which count); defined only for
          a cell that ran, and is valid at, every client count. A cell with an aborted
          client at any count has no R_peak: taking the highest of its remaining valid
          counts would compare it at a lower load than the others
  R_c     TPS at client count c
Effects are computed on log2 of the response and reported as ratios 2^effect.

Factorial model (exact OLS on the 32 cells, a full 2^5 factorial; the columns are
orthogonal, asserted): every factor coded -1 (OFF; DEL: set) / +1 (ON; DEL: fn),
plus every product of these columns, 31 contrasts in all. A main effect is
mean(ON) - mean(OFF) over 16 cells each. An interaction is the half difference,
between the two levels of one factor, of the lower-order effect (nested for three
or more factors), so a T5R:DEL interaction is half of (DEL effect with T5R ON - DEL
effect with T5R OFF). In OLS terms effect = 2 * beta for every column.

Error model -- an ASSUMPTION, not a measurement: the 6 contrasts that involve >= 4
of the 5 factors (C(5,4) + C(5,5) = 5 + 1) are ASSUMED TO BE NOISE. They are left
out of the fit; the residual of the remaining 25 terms gives the per-cell noise SD
(6 df), and every effect has the same SE, 2 * SD / sqrt(32). 95% interval =
effect +- t(0.975, 6) * SE. Lenth's pseudo standard error over all 31 contrasts is
a cross-check. The run-to-run SD measured by the replicate pairs is reported next
to the pooled one. A response is estimated only when all 32 cells are valid for
it; otherwise the non-valid cells are listed.

Add-one / leave-one-out follow the agreed linear history
  <s>300 -> +T5R <s>301 -> +T6R <s>303 -> +T7R <s>307 -> +DEL (fn) <s>323 -> +SH8
  <s>331
Add-one is each step's ratio against the previous cell of the history;
leave-one-out is <s>331 against the cell with one factor OFF (-DEL: T1 mode set).
Both at R_peak and at every client count; a row whose cells have not run says so.

Output, all in analysis/figures/ablation/ (side a) or analysis/figures/ablation_b/
(side b) (this script owns the directory's *.png, *.pdf and *.csv): figures as
PNG (dpi 200) + PDF, one chart per file, and
CSV tables. The module docstring of plot_results.py documents the palette; the
extra roles used here are the documented diverging pair (blue <-> red with the
neutral band grey midpoint) and the status "critical" red for non-valid points.
"""

import argparse
import math
import re
import sys
import time
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

# plot_results is imported from its own directory; do not leave a __pycache__ there.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import plot_results as pr  # noqa: E402  (also applies the shared rcParams)

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize, to_hex  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

# (manifest column, short label); list index = mask bit.
BINARY = [("t5_routing", "T5R"), ("t6_rollup", "T6R"), ("t7_routing", "T7R"),
          ("shards8", "SH8")]
SHORT = [s for _, s in BINARY]
NB = len(BINARY)
T1_COLUMN = "t1_mode"
T1_MODES = ["set", "fn"]                   # list index = m = level of DEL
DEL = "DEL"                                # the T1 mode as a binary factor
FACTORS = SHORT + [DEL]                    # factor k is bit k of Cell.bits
NF = len(FACTORS)
MAIN = FACTORS                             # main effects, in report order
N_MASKS = 2 ** NB
N_CELLS = N_MASKS * len(T1_MODES)          # 32 = 2^5
MANIFEST_COLUMNS = ["experiment"] + [f for f, _ in BINARY] + [T1_COLUMN, "source"]
CELL_OFFSET = 300            # factorial cell name: expt_<side><300 + 16*m + mask>
# side (workload) -> (manifest file in ablation/, output directory in analysis/figures/)
SIDES = {"a": ("manifest.csv", "ablation"), "b": ("manifest_b.csv", "ablation_b")}

# Every contrast: a tuple of indices into FACTORS, by number of factors involved,
# then without / with DEL, then combination of the binary factors.
TERMS = [combo + ((NB,) if with_del else ())
         for order in range(1, NF + 1)
         for with_del in (False, True)
         for combo in combinations(range(NB), order - with_del)
         if combo or with_del]
POOL_MIN_ORDER = 4           # contrasts among >= 4 of the 5 factors form the error pool
DF_POOLED = sum(1 for t in TERMS if len(t) >= POOL_MIN_ORDER)
assert len(TERMS) == N_CELLS - 1 and DF_POOLED == 6, (len(TERMS), DF_POOLED)
T_975 = 2.447                # t(0.975, 6), for DF_POOLED = 6

# The agreed linear history of optimisations: the factor added at each step.
HISTORY = ["T5R", "T6R", "T7R", DEL, "SH8"]
HISTORY_INDICES = [300, 301, 303, 307, 323, 331]
LEAVE_ONE_OUT_INDICES = [330, 329, 327, 323, 315]   # T5R, T6R, T7R, SH8, DEL OFF

TX_EFFECT_CLIENTS = (1, 64)
REPLICATE_TOLERANCE = 0.02   # CLAUDE.md: same code within ~2% at 1 client

SLOT1 = pr.CATEGORICAL[0]
DIV_LOW, DIV_MID, DIV_HIGH = pr.CATEGORICAL[7], pr.BAND, pr.CATEGORICAL[0]
CRITICAL = "#d03b3b"         # documented status "critical"; always paired with a label
ERROR_MODEL = (f"assumed noise: the {DF_POOLED} interactions among >= 4 of the 5 factors "
               f"({', '.join(FACTORS)})")
POOL_NOTE = (f"ASSUMPTION: the {DF_POOLED} interaction contrasts among 4 or 5 of the 5 factors "
             f"({', '.join(FACTORS)}) are noise; SE is the OLS SE from the residual of a fit "
             f"without them ({DF_POOLED} df, t(0.975, {DF_POOLED}) = {T_975}).")
NOT_RUN = "not run yet"


# ---- Manifest --------------------------------------------------------------
@dataclass(frozen=True)
class Cell:
    side: str                 # workload, a or b
    name: str                 # expt_a315, or expt_a300_1 for a replicate
    index: int                # 315; a replicate has its original's index
    mask: int                 # binary factors, bit k = BINARY[k]
    mode: int                 # T1 mode, index into T1_MODES (level of DEL)
    replicate_of: str | None  # id of the original cell, e.g. "a300"
    run: int | None           # replicate number k of expt_<side><index>_<k>; None for a cell
    path: Path

    @property
    def id(self):
        base = f"{self.side}{self.index}"
        return base if self.run is None else f"{base}_{self.run}"

    @property
    def bits(self):
        """All five factors, bit k = FACTORS[k]; the cell index is CELL_OFFSET + bits."""
        return self.mask | self.mode << NB

    @property
    def levels(self):
        return tuple((self.bits >> k) & 1 for k in range(NF))

    @property
    def t1_mode(self):
        return T1_MODES[self.mode]

    @property
    def label(self):
        on = [FACTORS[k] for k in range(NF) if self.levels[k]]
        return "+".join(on) if on else "base"


def cell_index(mask, mode):
    return CELL_OFFSET + N_MASKS * mode + mask


def read_manifest(repo, side):
    """Factorial cells of one side ordered by index (row = 16*m + mask), and replicates.

    Raises on any inconsistency. A listed cell whose directory is absent is kept:
    it has not been run yet (load() reports it).
    """
    path = repo / "ablation" / SIDES[side][0]
    prefix = f"expt_{side}"
    replicate_source = re.compile(rf"^replicate of ({prefix}\d+)$")
    ablation_name = re.compile(rf"^{prefix}(\d+)$")
    replicate_name = re.compile(rf"^{prefix}(\d+)_([1-9]\d*)$")   # k-th replicate of <index>
    if not path.is_file():
        raise FileNotFoundError(f"missing ablation manifest: {path}")
    m = pd.read_csv(path, dtype=str)
    if list(m.columns) != MANIFEST_COLUMNS:
        raise RuntimeError(f"{path}: columns {list(m.columns)} != {MANIFEST_COLUMNS}")
    if m.experiment.duplicated().any():
        raise RuntimeError(f"{path}: duplicate experiments "
                           f"{sorted(m.experiment[m.experiment.duplicated()])}")
    cells, replicates = {}, []
    for r in m.itertuples(index=False):
        rep = replicate_source.match(r.source)
        name_m = (replicate_name if rep else ablation_name).match(r.experiment)
        if not name_m:
            raise RuntimeError(f"{path}: experiment {r.experiment!r} with source {r.source!r} "
                               f"is not " + (f"{prefix}<integer>_<k>, k >= 1" if rep
                                             else f"{prefix}<integer>"))
        levels = tuple(int(getattr(r, f)) for f, _ in BINARY)
        if any(v not in (0, 1) for v in levels):
            raise RuntimeError(f"{path}: {r.experiment} has binary levels {levels}, not 0/1")
        t1 = getattr(r, T1_COLUMN)
        if t1 not in T1_MODES:
            raise RuntimeError(f"{path}: {r.experiment} has t1_mode {t1!r}, not one of {T1_MODES}")
        mask = sum(v << k for k, v in enumerate(levels))
        mode = T1_MODES.index(t1)
        index = int(name_m.group(1))
        if rep:
            orig = f"{prefix}{index}"
            if rep.group(1) != orig:
                raise RuntimeError(f"{path}: {r.experiment} is named as a replicate of {orig} "
                                   f"but its source says {r.source!r}")
            replicates.append((Cell(side, r.experiment, index, mask, mode, None,
                                    int(name_m.group(2)), repo / r.experiment), orig))
            continue
        cell = Cell(side, r.experiment, index, mask, mode, None, None, repo / r.experiment)
        if index != cell_index(mask, mode):
            raise RuntimeError(f"{path}: {r.experiment} should be named "
                               f"{prefix}{cell_index(mask, mode)} for mask {mask}, t1_mode {t1}")
        cells[cell.bits] = cell
    if len(cells) != N_CELLS:
        raise RuntimeError(f"{path}: {len(cells)} factorial cells, expected {N_CELLS}")
    by_name = {c.name: c for c in cells.values()}
    reps = []
    for rc, orig in replicates:
        if orig not in by_name:
            raise RuntimeError(f"{path}: {rc.name} replicates {orig}, which is not a factorial cell")
        o = by_name[orig]
        if (o.mask, o.mode) != (rc.mask, rc.mode):
            raise RuntimeError(f"{path}: {rc.name} levels ({rc.label}) != {orig} ({o.label})")
        reps.append(Cell(side, rc.name, rc.index, rc.mask, rc.mode, o.id, rc.run, rc.path))

    # Every directory of this side named as a grid cell or as a replicate of one
    # must be listed. A replicate of an experiment outside the grid (expt_a0_1 of
    # the base design expt_a0) is not part of the ablation.
    listed = set(m.experiment)
    lo, hi = CELL_OFFSET, CELL_OFFSET + N_CELLS
    stray = sorted(p.name for p in repo.iterdir()
                   if p.is_dir() and p.name not in listed
                   and (g := replicate_name.match(p.name) or ablation_name.match(p.name))
                   and lo <= int(g.group(1)) < hi)
    if stray:
        raise RuntimeError(f"{path} does not list ablation directories {stray}")
    return (sorted(cells.values(), key=lambda c: c.index),
            sorted(reps, key=lambda c: (c.index, c.run)))


# ---- Loading and responses -------------------------------------------------
def not_run_reason(c):
    """Why a cell has no results yet, or None when it has a finished client count."""
    if not c.path.is_dir():
        return f"{NOT_RUN} (no directory)"
    slurm = c.path / "slurm-results"
    if not slurm.is_dir():
        return f"{NOT_RUN} (no slurm-results/)"
    # run.sh creates slurm-results/job-<id>/ when the job starts but benchmark-results/
    # only after the schema, data load and plans (minutes later); until then the cell
    # has no result. A job that died in that phase stays in this state, so the reason
    # names the job. Zero or several job-*/ still raise in results_dir.
    jobs = [p for p in slurm.glob("job-*") if p.is_dir()]
    if len(jobs) == 1 and not (jobs[0] / "benchmark-results").is_dir():
        return (f"{NOT_RUN} (no benchmark-results/ in {jobs[0].name}: running, or failed "
                "before the benchmark)")
    s_path = pr.results_dir(pr.Experiment(c.side, c.index, c.path)) / "summary.csv"
    # A job that is still on its first client count has written only the CSV
    # header; that is "not run yet", not a broken cell. A missing summary.csv
    # still raises in load_experiment.
    if s_path.is_file() and pd.read_csv(s_path).empty:
        return f"{NOT_RUN} (running: no client count finished)"
    return None


def load(cells):
    """(summary, tx, status) over every cell; status[id] is 'complete' or why not.

    summary and tx are None when no cell has results.
    """
    summaries, txs, status = [], [], {}
    for c in cells:
        reason = not_run_reason(c)
        if reason:
            status[c.id] = reason
            continue
        s, t = pr.load_experiment(pr.Experiment(c.side, c.index, c.path))
        for df in (s, t):
            # plot_results names a run <side><index>, which a replicate shares with its
            # original; every lookup here is by c.id, which tells them apart.
            df["exp"] = c.id
            df["label"] = c.label
        summaries.append(s)
        txs.append(t)
    if not summaries:
        return None, None, status
    summary = pd.concat(summaries, ignore_index=True)
    tx = pd.concat(txs, ignore_index=True)
    for col, df in (("overall_tps", summary), ("avg_latency_ms", tx)):
        bad = df[~(df[col] > 0) & df.valid]
        if not bad.empty:
            raise RuntimeError(f"valid points with non-positive or missing {col} cannot be "
                               f"log-transformed:\n{bad[['exp', 'clients', col]]}")
    tx_sets = tx.groupby("exp").transaction.apply(lambda s: tuple(sorted(set(s), key=pr.tx_key)))
    if tx_sets.nunique() != 1:
        raise RuntimeError(f"cells measure different transaction sets: {tx_sets.to_dict()}")
    clients = sorted(summary.clients.unique())
    for e, g in summary.groupby("exp"):
        gone = [n for n in clients if n not in set(g.clients)]
        status[e] = (f"{NOT_RUN} (partial: no data at {', '.join(map(str, gone))} clients)"
                     if gone else "complete")
    return summary, tx, status


def peak(summary, status, exp_id):
    """(R_peak, clients, None) of a complete cell valid at every count, else (nan, nan, reason)."""
    if status[exp_id] != "complete":
        return np.nan, np.nan, status[exp_id]
    g = summary[summary.exp == exp_id]
    if not g.valid.all():
        at = ", ".join(str(int(n)) for n in g.clients[~g.valid])
        return np.nan, np.nan, f"not valid at {at} clients: no R_peak"
    r = g.loc[g.overall_tps.idxmax()]
    return float(r.overall_tps), int(r.clients), None


def point(summary, status, exp_id, clients):
    """(TPS, None) when the point exists and is valid, else (nan, reason)."""
    if exp_id not in set(summary.exp):
        return np.nan, status[exp_id]
    r = summary[(summary.exp == exp_id) & (summary.clients == clients)]
    if r.empty:
        return np.nan, f"{NOT_RUN} (partial: no data at {clients} clients)"
    r = r.iloc[0]
    if not r.valid:
        return np.nan, f"not valid [exit {r.pgbench_exit_code}, {r.aborted_clients} aborted]"
    return float(r.overall_tps), None


def cells_table(summary, status, all_cells, clients):
    rows = []
    for c in all_cells:
        row = {"experiment": c.name, "exp": c.id, "mask": c.mask, "label": c.label,
               "replicate_of": c.replicate_of or ""}
        row.update({f: c.levels[k] for k, (f, _) in enumerate(BINARY)})
        row[T1_COLUMN] = c.t1_mode
        row["status"] = status[c.id]
        row["has_data"] = c.id in set(summary.exp)
        tps, at, _ = peak(summary, status, c.id)
        row["r_peak_tps"] = tps
        row["r_peak_clients"] = at
        for n in clients:
            row[f"tps_c{n}"] = point(summary, status, c.id, n)[0]
        rows.append(row)
    return pd.DataFrame(rows).astype({"r_peak_clients": "Int64"})


def validity_table(summary, all_cells, clients):
    rows = []
    loaded = set(summary.exp)
    for c in all_cells:
        for n in clients:
            r = summary[(summary.exp == c.id) & (summary.clients == n)]
            base = {"experiment": c.name, "exp": c.id, "label": c.label, "clients": n}
            if r.empty:
                base.update(state="no data" if c.id not in loaded else "client count not run")
                rows.append(base)
                continue
            r = r.iloc[0]
            base.update(state="valid" if r.valid else "not valid",
                        overall_tps=r.overall_tps, pgbench_exit_code=r.pgbench_exit_code,
                        aborted_clients=r.aborted_clients, failed_log_records=r.failed_log_records,
                        serialization_failures=r.serialization_failures,
                        deadlock_failures=r.deadlock_failures)
            rows.append(base)
    cols = ["experiment", "exp", "label", "clients", "state", "overall_tps",
            "pgbench_exit_code", "aborted_clients", "failed_log_records",
            "serialization_failures", "deadlock_failures"]
    v = pd.DataFrame(rows).reindex(columns=cols)
    for col in cols[6:]:
        v[col] = v[col].astype("Int64")
    return v


# ---- Factorial effects -----------------------------------------------------
def effect_name(term):
    return ":".join(FACTORS[k] for k in term)


def design(cells):
    """(32 x 31 contrast matrix), rows in `cells` order: each column is the product
    of the -1/+1 codes of its term's factors.

    Asserts that the columns and the intercept are mutually orthogonal, so OLS is
    exact per contrast.
    """
    X = np.array([[1 if lv else -1 for lv in c.levels] for c in cells], dtype=float)
    C = np.column_stack([X[:, list(t)].prod(axis=1) for t in TERMS])
    full = np.column_stack([np.ones(len(cells)), C])
    gram = full.T @ full
    off = gram - np.diag(np.diag(gram))
    assert np.abs(off).max() < 1e-9, "factorial contrast columns are not orthogonal"
    return C


def factorial_effects(y, cells):
    """All 31 effects of log2 response y (one value per cell, `cells` order).

    Exact OLS: the full model (intercept + 31 columns) is saturated and gives the
    effects (effect = 2 * beta, the difference between the -1 and +1 means); the
    reduced model without the 6 pooled columns gives the residual SD.
    """
    C = design(cells)
    n = len(cells)
    full = np.column_stack([np.ones(n), C])
    beta = np.linalg.lstsq(full, y, rcond=None)[0][1:]
    effect = 2 * beta
    pooled = np.array([len(t) >= POOL_MIN_ORDER for t in TERMS])
    reduced = full[:, np.r_[True, ~pooled]]
    resid = y - reduced @ np.linalg.lstsq(reduced, y, rcond=None)[0]
    sigma = math.sqrt(float(resid @ resid) / DF_POOLED)
    k = 2 / math.sqrt(n)        # SE of every effect per unit per-cell noise SD
    se = k * sigma
    # Lenth's PSE; every effect has the same variance, so no standardisation.
    a = np.abs(effect)
    s0 = 1.5 * np.median(a)
    pse = 1.5 * np.median(a[a < 2.5 * s0])
    df = pd.DataFrame({
        "effect": [effect_name(t) for t in TERMS],
        "order": [len(t) for t in TERMS],
        "effect_log2": effect,
        "in_error_pool": pooled,
    })
    df["ratio"] = 2 ** df.effect_log2
    df["se_log2"] = se
    df["ci95_low_ratio"] = 2 ** (df.effect_log2 - T_975 * se)
    df["ci95_high_ratio"] = 2 ** (df.effect_log2 + T_975 * se)
    df["t_pooled"] = df.effect_log2 / se
    df["lenth_pse_log2"] = pse
    df["effect_over_pse"] = df.effect_log2 / df.lenth_pse_log2
    df["residual_sd_log2"] = sigma
    df["df_pooled"] = DF_POOLED
    df["t_quantile"] = T_975
    df["error_model"] = ERROR_MODEL
    # lenth_sigma: Lenth's PSE as a per-cell SD, comparable with sigma.
    df.attrs.update(sigma=sigma, lenth_sigma=pse / k, grand_mean_log2=float(np.mean(y)))
    return df


def blockers(reasons):
    """Cells that block a response: not-run cells counted, the rest listed."""
    not_run = [e for e, r in reasons if r.startswith(NOT_RUN)]
    other = [f"{e} {r}" for e, r in reasons if not r.startswith(NOT_RUN)]
    out = [f"{len(not_run)} cells {NOT_RUN} ({', '.join(not_run)})"] if not_run else []
    return out + other


# ---- Formatting helpers ----------------------------------------------------
def fmt_ratio(r):
    return f"×{r:.2f}"


def fmt_ci(lo, hi):
    return f"[{lo:.2f}, {hi:.2f}]"


RATIO_TIERS = [
    [1 / 8, 1 / 4, 1 / 2, 1, 2, 4, 8],
    [1 / 8, 1 / 4, 1 / 3, 1 / 2, 2 / 3, 1, 1.5, 2, 3, 4, 8],
    [1 / 4, 1 / 3, 1 / 2, 2 / 3, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 2, 3, 4],
    [1 / 2, 2 / 3, 0.8, 0.9, 0.95, 1, 1.05, 1.1, 1.25, 1.5, 2],
    [0.9, 0.95, 0.98, 1, 1.02, 1.05, 1.1],
]


def ratio_tick_values(lo, hi, max_ticks=8):
    """(log2 positions, labels) of ratio ticks for log2 data in [lo, hi].

    The finest tier with at most max_ticks ticks, none closer than 1/12 of the span
    (so labels never touch); otherwise the coarsest tier.
    """
    chosen = [r for r in RATIO_TIERS[0] if lo <= math.log2(r) <= hi]
    for tier in reversed(RATIO_TIERS):
        t = [r for r in tier if lo <= math.log2(r) <= hi]
        if 2 <= len(t) <= max_ticks and np.diff(np.log2(t)).min() >= (hi - lo) / 12:
            chosen = t
            break
    labels = [f"×{r:.0f}" if abs(r - round(r)) < 1e-9 else f"×{r:.2f}" for r in chosen]
    return [math.log2(r) for r in chosen], labels


def ratio_ticks(ax, axis, lo, hi, max_ticks=8):
    """Ticks labelled as ratios on an axis whose data are log2 ratios, in [lo, hi]."""
    pos, labels = ratio_tick_values(lo, hi, max_ticks)
    if axis == "x":
        ax.set_xlim(lo, hi)
        ax.set_xticks(pos, labels)
    else:
        ax.set_ylim(lo, hi)
        ax.set_yticks(pos, labels)
    ax.minorticks_off()


def padded(lo, hi, frac=0.08, include_zero=True):
    if include_zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    span = hi - lo if hi > lo else 0.1
    return lo - frac * span, hi + frac * span


def diverging_cmap(reverse=False):
    colors = [DIV_LOW, DIV_MID, DIV_HIGH]
    return LinearSegmentedColormap.from_list("div", colors[::-1] if reverse else colors)


def clients_axis(ax, clients):
    ax.set_xticks([math.log2(c) for c in clients], [str(c) for c in clients])
    ax.set_xlabel("clients")


def normal_quantile(p):
    """Inverse standard normal CDF by bisection on math.erf (no scipy)."""
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def noise_note(eff, rep_sd):
    """Pooled residual SD next to the replicate-measured run-to-run SD."""
    s = (f"Per-cell noise SD from the pooled interactions: {eff.attrs['sigma']:.4f} log2 "
         f"(×{2 ** eff.attrs['sigma']:.3f}); ")
    if rep_sd is None:
        return s + "run-to-run SD from replicates: no replicate pair valid for this response."
    sd, n = rep_sd
    return s + (f"run-to-run SD measured by {n} replicate pair{'s' if n != 1 else ''}: "
                f"{sd:.4f} log2 (×{2 ** sd:.3f}).")


MAIN_EFFECT_DEF = (
    f"Main effect: mean log2 response of the {N_CELLS // 2} cells with the factor ON minus "
    f"the {N_CELLS // 2} with it OFF (DEL: delegated place_order, fn, vs set-based T1, set). "
    "Shown as 2^effect.")


# ---- Figures ---------------------------------------------------------------
def fig_main_effects_peak(eff, rep_sd, out):
    main = eff[eff.order == 1].set_index("effect").loc[MAIN].reset_index()
    n = len(MAIN)
    width = 6.6
    fig, ax = plt.subplots(figsize=(width, 3.1))
    y = np.arange(n)[::-1]
    lo = np.log2(main.ci95_low_ratio.to_numpy())
    hi = np.log2(main.ci95_high_ratio.to_numpy())
    e = main.effect_log2.to_numpy()
    ax.axvline(0, color=pr.INK_2, lw=0.8, zorder=1)
    ax.hlines(y, lo, hi, color=SLOT1, lw=2, zorder=2)
    ax.scatter(e, y, s=40, color=SLOT1, edgecolor=pr.SURFACE, linewidth=1.2, zorder=3)
    xlo, xhi = padded(lo.min(), hi.max())
    xhi += 0.55 * (xhi - xlo)                     # room for the value labels
    ratio_ticks(ax, "x", xlo, xhi)
    for yi, h, r in zip(y, hi, main.itertuples()):
        ax.annotate(f"{fmt_ratio(r.ratio)}  {fmt_ci(r.ci95_low_ratio, r.ci95_high_ratio)}",
                    xy=(h, yi), xytext=(6, 0), textcoords="offset points", va="center",
                    fontsize=7.5, color=pr.INK_2)
    ax.set_yticks(y, main.effect)
    ax.set_ylim(-0.6, n - 0.4)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("ratio of peak TPS, ON / OFF (log scale)")
    ax.set_title(f"Main effects on peak throughput over {N_CELLS} cells, with 95% intervals",
                 loc="left")
    pr.caption(ax, [
        MAIN_EFFECT_DEF + " R_peak = highest TPS over the client counts, only for cells valid at every "
        f"count (peak client count differs by cell; see cells.csv). Interval = effect ± {T_975} × SE. "
        + POOL_NOTE,
        noise_note(eff, rep_sd) + " Cross-check, Lenth's estimate of the same per-cell SD "
        f"from all {len(TERMS)} contrasts: {eff.attrs['lenth_sigma']:.4f} log2 (PSE in "
        "effects_peak.csv).",
    ], width)
    pr.save(fig, out, "main_effects_peak")


# Two-factor interaction grid: rows x columns; every pair of the four mask factors
# once (lower triangle) plus each of them with DEL, so every two-factor interaction.
GRID_ROWS = SHORT[1:] + [DEL]
GRID_COLS = SHORT


def grid_term(row, col):
    """Effect name at (row, col), or None for cells the grid leaves empty."""
    if row in SHORT and SHORT.index(col) >= SHORT.index(row):
        return None
    return f"{col}:{row}"


def fig_interactions_peak(eff, out):
    two = eff[eff.order == 2].set_index("effect")
    vmax = eff.effect_log2.abs().max()
    norm = Normalize(-vmax, vmax)
    cmap = diverging_cmap()
    nr, nc = len(GRID_ROWS), len(GRID_COLS)
    g = np.full((nr, nc), np.nan)
    for i, row in enumerate(GRID_ROWS):
        for j, col in enumerate(GRID_COLS):
            t = grid_term(row, col)
            if t:
                g[i, j] = two.loc[t, "effect_log2"]
    width = 5.6
    fig, ax = plt.subplots(figsize=(width, 4.8))
    im = ax.imshow(np.ma.masked_invalid(g), cmap=cmap, norm=norm, aspect="equal")
    for i, row in enumerate(GRID_ROWS):
        for j, col in enumerate(GRID_COLS):
            t = grid_term(row, col)
            if not t:
                continue
            r = two.loc[t]
            ink = pr.ink_for(to_hex(cmap(norm(g[i, j]))))
            ax.text(j, i - 0.12, fmt_ratio(r.ratio), ha="center", va="center", fontsize=8,
                    color=ink)
            ax.text(j, i + 0.2, fmt_ci(r.ci95_low_ratio, r.ci95_high_ratio), ha="center",
                    va="center", fontsize=6, color=ink)
    ax.axhline(len(SHORT) - 1.5, color=pr.INK_2, lw=0.8)   # binary rows | T1 rows
    ax.set_xticks(range(nc), GRID_COLS)
    ax.set_yticks(range(nr), GRID_ROWS)
    ax.tick_params(length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(f"Two-factor interactions on peak throughput over {N_CELLS} cells", loc="left")
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cb.outline.set_visible(False)
    pos, labels = ratio_tick_values(-vmax, vmax, max_ticks=7)
    cb.set_ticks(pos, labels=labels)
    cb.set_label("interaction ratio (log scale)", color=pr.INK_2)
    pr.caption(ax, [
        "Cell (row, column) = interaction, shown as 2^effect with its 95% interval: half "
        "the difference between the column factor's log2 effect with the row factor ON and "
        "with it OFF (DEL ON = delegated place_order, fn; OFF = set-based T1). Blue: the "
        "pair together gives more peak TPS than the two main effects "
        f"predict; red: less. The colour scale spans the largest of all {len(TERMS)} effects, "
        "so interactions and main effects share one scale. " + POOL_NOTE,
    ], width, offset_pt=14)
    pr.save(fig, out, "interactions_peak")


def fig_half_normal_peak(eff, out):
    d = eff.assign(abs_t=eff.t_pooled.abs()).sort_values("abs_t").reset_index(drop=True)
    m = len(d)
    d["q"] = [normal_quantile(0.5 + 0.5 * (i + 0.5) / m) for i in range(m)]
    d["beyond"] = d.abs_t > T_975
    width = 6.6
    fig, ax = plt.subplots(figsize=(width, 8.5))
    fig.subplots_adjust(top=0.95, bottom=0.13)
    xmax = d.abs_t.max()
    xlo, xhi = -0.04 * xmax, 1.06 * xmax
    qmax = d.q.max() * 1.03
    ax.plot([0, qmax], [0, qmax], color=pr.INK_2, lw=1, zorder=1)
    for pool in (False, True):
        for beyond in (False, True):
            p = d[(d.in_error_pool == pool) & (d.beyond == beyond)]
            c = SLOT1 if beyond else pr.MUTED
            if pool:
                ax.scatter(p.abs_t, p.q, s=34, facecolor=pr.SURFACE, edgecolor=c,
                           linewidth=1.4, zorder=3)
            else:
                ax.scatter(p.abs_t, p.q, s=34, color=c, edgecolor=pr.SURFACE,
                           linewidth=1.2, zorder=3)
    texts = []
    mid = (xlo + xhi) / 2
    for r in d.itertuples():
        right = r.abs_t < mid
        texts.append(ax.annotate(f"{r.effect} {fmt_ratio(r.ratio)}", xy=(r.abs_t, r.q),
                                 xytext=(6 if right else -6, 0), textcoords="offset points",
                                 ha="left" if right else "right", va="center", fontsize=6.3,
                                 color=pr.INK_2))
    ax.set_xlim(xlo, xhi)
    ax.set_ylim(0, qmax)
    ax.set_xlabel("|effect| / SE  (SE from the pooled noise, the same for every effect)")
    ax.set_ylabel("half-normal quantile")
    ax.set_title(f"Half-normal plot of all {m} effects on peak throughput", loc="left")
    handles = [
        Line2D([], [], ls="", marker="o", ms=5.5, color=SLOT1, mec=pr.SURFACE,
               label="95% interval excludes ×1"),
        Line2D([], [], ls="", marker="o", ms=5.5, color=pr.MUTED, mec=pr.SURFACE,
               label="95% interval includes ×1"),
        Line2D([], [], ls="", marker="o", ms=5.5, mfc=pr.SURFACE, mec=pr.INK_2, mew=1.3,
               label="hollow: 4- or 5-factor, in the error pool"),
        Line2D([], [], color=pr.INK_2, lw=1, label="|effect| / SE = quantile"),
    ]
    ax.legend(handles=handles, loc="lower right")
    pr.caption(ax, [
        "Each label gives the signed effect as a ratio (ON / OFF; DEL delegated / set). "
        "Every contrast is a -1/+1 column over the same cells, so all effects share one SE; "
        "effects on the line behave like noise, effects far right of it do not. " + POOL_NOTE,
    ], width, offset_pt=30)
    pr.check_labels_disjoint(fig, texts)
    pr.save(fig, out, "half_normal_peak")


def fig_main_effects_by_clients(by_c, skipped, out):
    clients = sorted(by_c)
    width = 7.2
    fig, ax = plt.subplots(figsize=(width, 4.4))
    fig.subplots_adjust(right=0.74)
    ax.axhline(0, color=pr.INK_2, lw=0.8, zorder=1)
    ends, allv = [], []
    for k, s in enumerate(MAIN):
        dodge = (k - (len(MAIN) - 1) / 2) * 0.05
        xs = np.array([math.log2(c) + dodge for c in clients])
        rows = [by_c[c].set_index("effect").loc[s] for c in clients]
        e = np.array([r.effect_log2 for r in rows])
        lo = np.log2([r.ci95_low_ratio for r in rows])
        hi = np.log2([r.ci95_high_ratio for r in rows])
        allv += list(lo) + list(hi)
        col = pr.CATEGORICAL[k]
        ax.vlines(xs, lo, hi, color=col, lw=1, zorder=2)
        ax.plot(xs, e, color=col, lw=1.5, zorder=2)
        ax.scatter(xs, e, s=30, color=col, edgecolor=pr.SURFACE, linewidth=1.2, zorder=3)
        ends.append((s, xs[-1], e[-1], col))
    ylo, yhi = padded(min(allv), max(allv))
    ratio_ticks(ax, "y", ylo, yhi)
    clients_axis(ax, clients)
    ax.set_xlim(math.log2(clients[0]) - 0.4, math.log2(clients[-1]) + 0.4)
    ax.set_ylabel("ratio of TPS, ON / OFF (log scale)")
    ax.set_title(f"Main effects on throughput at each client count with all {N_CELLS} "
                 "cells valid", loc="left")
    pr.label_line_ends(ax, ends)
    pr.check_labels_disjoint(fig, list(ax.texts))
    handles = [Line2D([], [], color=pr.CATEGORICAL[k], marker="o", ms=5, mec=pr.SURFACE,
                      label=s) for k, s in enumerate(MAIN)]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.12, 1.0))
    pr.caption(ax, [
        "Effect per client count c, on log2 TPS at c. " + MAIN_EFFECT_DEF + " Vertical bars "
        f"are 95% intervals (effect ± {T_975} × SE at that c); points are offset sideways per "
        "factor so the bars do not overlap. " + POOL_NOTE,
        ("Not estimated: " + "; ".join(f"{c} clients: {', '.join(v)}"
                                       for c, v in skipped.items()) + ".")
        if skipped else "",
    ], width)
    pr.save(fig, out, "main_effects_by_clients")


def fig_ratio_bars(peak_rows, title, note, out, name):
    """Horizontal bars of the R_peak ratio per history step from a ×1 baseline.

    peak_rows: the r_peak rows of add_one / leave_one_out, in display order.
    """
    n = len(peak_rows)
    width = 6.6
    fig, ax = plt.subplots(figsize=(width, 1.2 + 0.32 * n))
    y = np.arange(n)[::-1]
    vals = [math.log2(r) if pd.notna(r) else np.nan for r in peak_rows.ratio]
    finite = [v for v in vals if not np.isnan(v)] or [0.0]   # no row has a ratio yet
    lo, hi = min(min(finite), 0.0), max(max(finite), 0.0)
    span = max(hi - lo, 0.1)
    # Room on each side for the status text and the tip labels.
    xlo, xhi = lo - (0.2 if lo < 0 else 0.05) * span, hi + (0.2 if hi > 0 else 0.05) * span
    if hi <= 0:
        xhi += 0.25 * span                            # status text runs right of ×1
    ratio_ticks(ax, "x", xlo, xhi)
    ax.axvline(0, color=pr.INK_2, lw=0.8, zorder=3)
    labels = []
    for yi, r, v in zip(y, peak_rows.itertuples(), vals):
        labels.append(f"{r.step}  ({r.cell} / {r.reference})")
        if np.isnan(v):
            ax.text(0, yi, f"  {r.status}", va="center", ha="left", fontsize=7,
                    color=pr.MUTED)
            continue
        ax.barh(yi, v, height=0.5, color=SLOT1, zorder=2)
        ax.annotate(fmt_ratio(2 ** v), xy=(v, yi), xytext=(4 if v >= 0 else -4, 0),
                    textcoords="offset points", ha="left" if v >= 0 else "right",
                    va="center", fontsize=7.5, color=pr.INK_2)
    ax.set_yticks(y, labels)
    ax.set_ylim(-0.6, n - 0.4)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("ratio of R_peak (log scale)")
    ax.set_title(title, loc="left")
    pr.caption(ax, [note], width)
    pr.save(fig, out, name)


def fig_peak_tps_by_cell(cells_df, out):
    d = cells_df[cells_df.has_data].copy()
    d["name"] = [f"{r.label}  {r.exp}" + (" (replicate)" if r.replicate_of else "")
                 for r in d.itertuples()]
    d = d.sort_values("r_peak_tps", ascending=False, na_position="last").reset_index(drop=True)
    n = len(d)
    width = 7.6
    fig, ax = plt.subplots(figsize=(width, 1.4 + 0.24 * n))
    y = np.arange(n)[::-1]
    xmax = d.r_peak_tps.max() if d.r_peak_tps.notna().any() else 1.0
    for yi, r in zip(y, d.itertuples()):
        if pd.isna(r.r_peak_tps):
            text = " no valid point" if r.status == "complete" else f" {r.status}"
            ax.text(0, yi, text, va="center", fontsize=7, color=pr.MUTED)
            continue
        col = pr.BLUE_RAMP[3] if r.replicate_of else SLOT1
        ax.barh(yi, r.r_peak_tps, height=0.62, color=col, zorder=2)
        ax.annotate(f"{r.r_peak_tps:,.0f} at {r.r_peak_clients}", xy=(r.r_peak_tps, yi),
                    xytext=(4, 0), textcoords="offset points", va="center", fontsize=7,
                    color=pr.INK_2)
    ax.set_xlim(0, xmax * 1.18)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_yticks(y, d.name)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("peak throughput R_peak (TPS)")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_title(f"Peak throughput of the {n} ablation runs with results", loc="left")
    if d.replicate_of.astype(bool).any():
        ax.legend(handles=[Patch(color=SLOT1, label="factorial cell"),
                           Patch(color=pr.BLUE_RAMP[3], label="replicate")],
                  loc="lower right")
    missing = list(cells_df.loc[~cells_df.has_data, "exp"])
    pr.caption(ax, [
        "R_peak = highest TPS over the client counts, only for cells valid at every "
        "client count (a cell with an aborted client has none); the value label gives it and the client count where it occurs. "
        "Labels list the optimisations ON (base = none; DEL = delegated place_order).",
        f"No results yet: {', '.join(missing)}." if missing else "",
    ], width)
    pr.save(fig, out, "peak_tps_by_cell")


def fig_validity_map(vt, all_cells, clients, out):
    rows = [c.id for c in all_cells]
    labels = [f"{c.id}  {c.label}" for c in all_cells]
    n, m = len(rows), len(clients)
    width = 2.6 + 0.95 * m
    fig, ax = plt.subplots(figsize=(width, 1.2 + 0.24 * n))
    idx = vt.set_index(["exp", "clients"])
    for i, e in enumerate(rows):
        for j, c in enumerate(clients):
            r = idx.loc[(e, c)]
            if r.state == "valid":
                fill, text, ink = pr.BAND, f"{r.overall_tps:,.0f}", pr.INK_2
            elif r.state == "not valid":
                fill = CRITICAL
                text = f"exit {r.pgbench_exit_code}, {r.aborted_clients} abrt"
                ink = pr.ink_for(CRITICAL)
            else:
                fill, text, ink = pr.SURFACE, "no data", pr.MUTED
            ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor=fill,
                                   edgecolor=pr.SURFACE, linewidth=1.5))
            ax.text(j, i, text, ha="center", va="center", fontsize=6.3, color=ink)
    ax.set_xlim(-0.5, m - 0.5)
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_xticks(range(m), [str(c) for c in clients])
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")
    ax.set_xlabel("clients")
    ax.set_yticks(range(n), labels)
    ax.tick_params(length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("Validity of every ablation cell at every client count", loc="left", pad=8)
    ax.legend(handles=[Patch(color=pr.BAND, label="valid (TPS shown)"),
                       Patch(color=CRITICAL, label="not valid (exit code, aborted clients)"),
                       Patch(facecolor=pr.SURFACE, edgecolor=pr.AXIS, label="no data")],
              loc="upper left", bbox_to_anchor=(0, 0), ncol=3, fontsize=7)
    pr.caption(ax, [f"Not valid = {pr.INVALID_RULE}; the numbers are also in validity.csv."],
               width, offset_pt=26)
    pr.save(fig, out, "validity_map")


def fig_transaction_effects(te, clients, vmax, transactions, out):
    g = te.pivot(index="factor", columns="transaction", values="effect_log2").reindex(
        index=MAIN, columns=transactions).to_numpy(dtype=float)
    norm = Normalize(-vmax, vmax)
    cmap = diverging_cmap(reverse=True)       # lower latency (ratio < 1) is blue
    width = 1.6 + 0.66 * len(transactions)
    fig, ax = plt.subplots(figsize=(width, 3.3))
    im = ax.imshow(g, cmap=cmap, norm=norm, aspect="auto")
    for i in range(len(MAIN)):
        for j in range(len(transactions)):
            fill = to_hex(cmap(norm(g[i, j])))
            ax.text(j, i, fmt_ratio(2 ** g[i, j]), ha="center", va="center", fontsize=7,
                    color=pr.ink_for(fill))
    ax.set_xticks(range(len(transactions)), transactions)
    ax.set_yticks(range(len(MAIN)), MAIN)
    ax.tick_params(length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(f"Main effects on average latency per transaction, {pr.clients_label(clients)}",
                 loc="left")
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cb.outline.set_visible(False)
    pos, labels = ratio_tick_values(-vmax, vmax, max_ticks=7)
    cb.set_ticks(pos, labels=labels)
    cb.set_label("latency ratio ON / OFF (log scale)", color=pr.INK_2)
    pr.caption(ax, [
        f"Ratio = 2^effect on log2 avg_latency_ms, all {N_CELLS} cells valid at "
        f"{pr.clients_label(clients)}. " + MAIN_EFFECT_DEF + " Blue = lower latency with the "
        "optimisation ON, red = higher. Colour scale shared by every transaction-effect "
        "heatmap. Intervals are in the CSV of the same name. " + POOL_NOTE,
    ], width, offset_pt=22)
    pr.save(fig, out, f"transaction_effects_c{clients}")


def fig_replicate_check(rep, lat1, out):
    tps = rep[rep.metric == "overall_tps"]
    pairs = list(dict.fromkeys(tps.pair))
    clients = sorted(tps.clients.unique())
    width = 7.2
    fig, ax = plt.subplots(figsize=(width, 3.8))
    fig.subplots_adjust(right=0.74)
    tol = math.log2(1 + REPLICATE_TOLERANCE)
    ax.axhspan(-tol, tol, color=pr.BAND, zorder=0, lw=0)
    ax.axhline(0, color=pr.INK_2, lw=0.8, zorder=1)
    allv = [-tol, tol]
    for k, p in enumerate(pairs):
        d = tps[tps.pair == p].set_index("clients").reindex(clients)
        v = np.log2(d.ratio.to_numpy(dtype=float))
        x = np.log2(clients)
        col = pr.CATEGORICAL[k]
        ax.plot(x, v, color=col, lw=1.5, zorder=2)
        ax.scatter(x, v, s=30, color=col, edgecolor=pr.SURFACE, linewidth=1.2, zorder=3)
        allv += [a for a in v if not np.isnan(a)]
    ylo, yhi = padded(min(allv), max(allv), frac=0.15)
    ratio_ticks(ax, "y", ylo, yhi)
    clients_axis(ax, clients)
    ax.set_ylabel("TPS ratio, replicate / original (log scale)")
    ax.set_title("Throughput of each replicate relative to its original run", loc="left")
    handles = [Line2D([], [], color=pr.CATEGORICAL[k], marker="o", ms=5, mec=pr.SURFACE,
                      label=p) for k, p in enumerate(pairs)]
    handles.append(Patch(color=pr.BAND, label=f"within ±{REPLICATE_TOLERANCE:.0%}"))
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.02, 1.0))
    parts = ["Ratio at each client count where both runs are valid; a missing point means "
             "one of the two is not valid there. A replicate is a second run of the same code, "
             "so every transaction is compared."]
    for p in pairs:
        d = lat1[lat1.pair == p]
        if not d.empty:
            parts.append(f"{p} avg latency ratio at 1 client: "
                         + ", ".join(f"{r.transaction} {fmt_ratio(r.ratio)}"
                                     for r in d.itertuples() if pd.notna(r.ratio)) + ".")
    pr.caption(ax, parts, width)
    pr.save(fig, out, "replicate_check")


# ---- Linear history: add-one and leave-one-out ------------------------------
def history_cells(by_bits):
    """The cumulative cells of HISTORY, base first; asserted against HISTORY_INDICES."""
    bits = 0
    path = [by_bits[bits]]
    for step in HISTORY:
        bits |= 1 << FACTORS.index(step)
        path.append(by_bits[bits])
    indices = [c.index for c in path]
    if indices != HISTORY_INDICES:
        raise RuntimeError(f"linear history derived from the manifest {indices} "
                           f"!= {HISTORY_INDICES}")
    return path


def leave_one_out_cells(by_bits):
    """[(step, cell without it)] for the all-ON cell; asserted against LEAVE_ONE_OUT_INDICES."""
    full = 2 ** NF - 1
    out = [(FACTORS[k], by_bits[full ^ (1 << k)]) for k in range(NF)]
    indices = [c.index for _, c in out]
    if indices != LEAVE_ONE_OUT_INDICES:
        raise RuntimeError(f"leave-one-out cells derived from the manifest {indices} "
                           f"!= {LEAVE_ONE_OUT_INDICES}")
    return out


def pair_rows(summary, status, cell, ref, step, clients):
    """R_peak and R_c ratio rows for one cell against one reference cell."""
    def row(response, ca, cr, ta, tr, reasons):
        why = [f"{e}: {r}" for e, r in reasons if r]
        return {"step": step, "cell": cell.id, "reference": ref.id, "response": response,
                "clients_cell": ca, "clients_reference": cr, "tps_cell": ta,
                "tps_reference": tr, "ratio": ta / tr if not why else np.nan,
                "status": "; ".join(why) if why else "ok"}
    pa, na, ra = peak(summary, status, cell.id)
    pb, nb, rb = peak(summary, status, ref.id)
    rows = [row("r_peak", na, nb, pa, pb, [(cell.id, ra), (ref.id, rb)])]
    for n in clients:
        a, ra = point(summary, status, cell.id, n)
        b, rb = point(summary, status, ref.id, n)
        rows.append(row(f"tps_c{n}", n, n, a, b, [(cell.id, ra), (ref.id, rb)]))
    return rows


def history_table(summary, status, pairs, clients):
    rows = []
    for step, cell, ref in pairs:
        rows += pair_rows(summary, status, cell, ref, step, clients)
    df = pd.DataFrame(rows)
    return df.astype({"clients_cell": "Int64", "clients_reference": "Int64"})


# ---- Replicates --------------------------------------------------------------
def replicate_tables(summary, tx, status, replicates, clients, transactions):
    rows, lat = [], []
    skipped = []
    loaded = set(summary.exp)
    for rc in replicates:
        orig = rc.replicate_of
        if rc.id not in loaded or orig not in loaded:
            skipped.append(f"{rc.id} / {orig}")
            continue
        pair = f"{rc.id} / {orig}"
        a, _, _ = peak(summary, status, rc.id)
        b, _, _ = peak(summary, status, orig)
        rows.append({"pair": pair, "metric": "r_peak", "transaction": "", "clients": pd.NA,
                     "original": b, "replicate": a, "ratio": a / b})
        for n in clients:
            a, b = point(summary, status, rc.id, n)[0], point(summary, status, orig, n)[0]
            rows.append({"pair": pair, "metric": "overall_tps", "transaction": "",
                         "clients": n, "original": b, "replicate": a, "ratio": a / b})
        for t in transactions:
            vals = []
            for e in (orig, rc.id):
                r = tx[(tx.exp == e) & (tx.clients == 1) & (tx.transaction == t)]
                vals.append(float(r.avg_latency_ms.iloc[0])
                            if not r.empty and bool(r.valid.iloc[0]) else np.nan)
            row = {"pair": pair, "metric": "avg_latency_ms", "transaction": t, "clients": 1,
                   "original": vals[0], "replicate": vals[1], "ratio": vals[1] / vals[0]}
            rows.append(row)
            lat.append(row)
    cols = ["pair", "metric", "transaction", "clients", "original", "replicate", "ratio"]
    rep = pd.DataFrame(rows, columns=cols).astype({"clients": "Int64"})
    return rep, pd.DataFrame(lat, columns=cols), skipped


def replicate_sd(rep, response):
    """(run-to-run SD of one cell's log2 response, pairs) from the replicate pairs, or None.

    A pair's log2 ratio has variance 2 sigma^2, so sigma = sqrt(mean(d^2) / 2).
    """
    if rep.empty:
        return None
    if response == "r_peak":
        d = rep[rep.metric == "r_peak"]
    else:
        d = rep[(rep.metric == "overall_tps") & (rep.clients == int(response[len("tps_c"):]))]
    v = np.log2(d.ratio.dropna().to_numpy(dtype=float))
    if len(v) == 0:
        return None
    return math.sqrt(float((v ** 2).mean()) / 2), len(v)


# ---- Driver ----------------------------------------------------------------
def print_effects(title, eff, rep_sd, max_order):
    print(f"\n{title}  (geometric mean {2 ** eff.attrs['grand_mean_log2']:.1f}; "
          f"per-cell noise SD {eff.attrs['sigma']:.4f} log2 from the {DF_POOLED} "
          f"interactions among >= 4 factors, ASSUMED noise; replicate run-to-run SD "
          + (f"{rep_sd[0]:.4f} log2 over {rep_sd[1]} pair(s)" if rep_sd else "n/a") + ")")
    for r in eff[eff.order <= max_order].itertuples():
        flag = "" if r.ci95_low_ratio <= 1 <= r.ci95_high_ratio else "  *"
        print(f"  {r.effect:<13} {fmt_ratio(r.ratio)}  95% "
              f"{fmt_ci(r.ci95_low_ratio, r.ci95_high_ratio)}  t={r.t_pooled:6.2f}  "
              f"e/PSE={r.effect_over_pse:6.2f}{flag}")


def run(repo, side, out):
    start = time.perf_counter()
    cells, replicates = read_manifest(repo, side)
    all_cells = cells + replicates
    out.mkdir(parents=True, exist_ok=True)
    # This script owns the directory: drop last run's outputs so a table or
    # figure that is no longer estimable does not survive as a stale file.
    for pattern in ("*.png", "*.pdf", "*.csv"):
        for f in out.glob(pattern):
            f.unlink()

    summary, tx, status = load(all_cells)
    if summary is None:
        print(f"no ablation cell of {SIDES[side][0]} has results yet under {repo}; "
              "nothing to analyse")
        return []
    clients = sorted(summary.clients.unique())
    transactions = sorted(tx.transaction.unique(), key=pr.tx_key)
    complete = [c.id for c in all_cells if status[c.id] == "complete"]
    print(f"{len(complete)} of {len(all_cells)} manifest entries complete; "
          f"client counts {clients}")
    for c in all_cells:
        if status[c.id] != "complete":
            print(f"  {c.id} {c.label}: {status[c.id]}")
    bad = summary[~summary.valid]
    for e, g in bad.groupby("exp", sort=False):
        print(f"  {e}: not valid at " + ", ".join(
            f"{r.clients} [exit {r.pgbench_exit_code}, {r.aborted_clients} aborted]"
            for r in g.itertuples()))

    cells_df = cells_table(summary, status, all_cells, clients)
    cells_df.to_csv(out / "cells.csv", index=False)
    vt = validity_table(summary, all_cells, clients)
    vt.to_csv(out / "validity.csv", index=False)
    fig_validity_map(vt, all_cells, clients, out)
    fig_peak_tps_by_cell(cells_df, out)

    by_bits = {c.bits: c for c in cells}
    hist = history_cells(by_bits)
    add_one = history_table(summary, status, [(f"+{s}", hist[i + 1], hist[i])
                                              for i, s in enumerate(HISTORY)], clients)
    final = hist[-1]
    loo = history_table(summary, status, [(f"-{s}", final, ref)
                                          for s, ref in leave_one_out_cells(by_bits)], clients)
    add_one.to_csv(out / "add_one.csv", index=False)
    loo.to_csv(out / "leave_one_out.csv", index=False)
    fig_ratio_bars(add_one[add_one.response == "r_peak"],
                   "Peak throughput gained by each step of the optimisation history",
                   "Ratio = R_peak of the cell after the step / R_peak of the cell before it, "
                   f"along {' -> +'.join([hist[0].id] + HISTORY)} (+DEL: T1 mode set -> fn). "
                   "R_peak = highest TPS over the client counts; the two peaks may "
                   "sit at different client counts (add_one.csv, also per client count).",
                   out, "add_one_peak")
    fig_ratio_bars(loo[loo.response == "r_peak"],
                   f"Peak throughput of {final.id} relative to the cell missing one optimisation",
                   f"Ratio = R_peak of {final.id} (every optimisation ON) / R_peak of the "
                   "cell with that one factor OFF (-DEL: T1 mode set instead of fn). R_peak = "
                   "highest TPS over the client counts, only for cells valid at every count "
                   "(leave_one_out.csv, also per client count).",
                   out, "leave_one_out_peak")
    for name, t in (("add-one", add_one), ("leave-one-out", loo)):
        print(f"\n{name} (R_peak ratio):")
        for r in t[t.response == "r_peak"].itertuples():
            v = fmt_ratio(r.ratio) if r.status == "ok" else r.status
            print(f"  {r.step:<5} {r.cell} / {r.reference}: {v}")

    rep, lat1, rep_skipped = replicate_tables(summary, tx, status, replicates, clients,
                                              transactions)
    rep.to_csv(out / "replicates.csv", index=False)
    if not rep.empty:
        fig_replicate_check(rep, lat1, out)
        print("\nreplicates (ratio replicate / original):")
        for p, g in rep.groupby("pair", sort=False):
            pk = g[g.metric == "r_peak"].ratio.iloc[0]
            t = g[g.metric == "overall_tps"]
            lt = g[g.metric == "avg_latency_ms"]
            print(f"  {p} R_peak {fmt_ratio(pk) if pd.notna(pk) else 'n/a'};  TPS:  "
                  + "  ".join(f"c{r.clients} {fmt_ratio(r.ratio)}" for r in t.itertuples()))
            print(f"  {p} avg latency c1:  " + "  ".join(f"{r.transaction} {fmt_ratio(r.ratio)}"
                                                         for r in lt.itertuples()))
        for resp in ["r_peak"] + [f"tps_c{n}" for n in clients]:
            sd = replicate_sd(rep, resp)
            if sd:
                print(f"  run-to-run SD of log2 {resp}: {sd[0]:.4f} ({sd[1]} pair(s))")
    if rep_skipped:
        print(f"replicate check: skipped {', '.join(rep_skipped)} (a run has no results yet)")

    effects_step(summary, tx, status, cells, clients, transactions, rep, out)

    names = sorted(p.name for p in out.iterdir() if p.suffix in (".png", ".csv"))
    print(f"\nwrote to {out} in {time.perf_counter() - start:.1f}s:\n  " + " ".join(names))
    return names


def effects_step(summary, tx, status, cells, clients, transactions, rep, out):
    reasons = [(c.id, peak(summary, status, c.id)[2]) for c in cells]
    blocked = [(e, r) for e, r in reasons if r]
    if blocked:
        print(f"\neffects on R_peak: not estimated; {'; '.join(blockers(blocked))}")
    else:
        y = np.log2([peak(summary, status, c.id)[0] for c in cells])
        eff = factorial_effects(y, cells)
        eff.insert(0, "response", "r_peak")
        sd = replicate_sd(rep, "r_peak")
        eff["replicate_sd_log2"] = sd[0] if sd else np.nan
        eff["replicate_pairs"] = sd[1] if sd else 0
        eff.to_csv(out / "effects_peak.csv", index=False)
        print_effects("effects on R_peak", eff, sd, max_order=3)
        fig_main_effects_peak(eff, sd, out)
        fig_interactions_peak(eff, out)
        fig_half_normal_peak(eff, out)

    by_c, skipped = {}, {}
    for n in clients:
        pts = [(c.id, point(summary, status, c.id, n)) for c in cells]
        blocked = [(e, r) for e, (_, r) in pts if r]
        if blocked:
            skipped[n] = blockers(blocked)
            print(f"effects at {n} clients: not estimated; {'; '.join(skipped[n])}")
            continue
        eff = factorial_effects(np.log2([v for _, (v, _) in pts]), cells)
        eff.insert(0, "response", f"tps_c{n}")
        sd = replicate_sd(rep, f"tps_c{n}")
        eff["replicate_sd_log2"] = sd[0] if sd else np.nan
        eff["replicate_pairs"] = sd[1] if sd else 0
        eff.to_csv(out / f"effects_c{n}.csv", index=False)
        by_c[n] = eff
        print_effects(f"effects on TPS at {n} clients", eff, sd, max_order=2)
    if by_c:
        fig_main_effects_by_clients(by_c, skipped, out)
    else:
        print(f"main effects by client count: no client count has all {N_CELLS} cells valid")

    tx_eff = {}
    for n in TX_EFFECT_CLIENTS:
        if n in skipped or n not in clients:
            print(f"transaction effects at {n} clients: not estimated "
                  f"({'; '.join(skipped.get(n, ['client count not run']))})")
            continue
        rows = []
        for t in transactions:
            d = tx[(tx.clients == n) & (tx.transaction == t)].set_index("exp").avg_latency_ms
            eff = factorial_effects(np.log2([d[c.id] for c in cells]), cells)
            main = eff[eff.order == 1].rename(columns={"effect": "factor",
                                                       "ratio": "latency_ratio"})
            main.insert(0, "transaction", t)
            main.insert(1, "clients", n)
            rows.append(main.drop(columns=["order", "in_error_pool"]))
        te = pd.concat(rows, ignore_index=True)
        te.to_csv(out / f"transaction_effects_c{n}.csv", index=False)
        tx_eff[n] = te
        print(f"\nmain effects on avg latency at {n} clients (ratio ON / OFF):")
        piv = te.pivot(index="factor", columns="transaction", values="latency_ratio")
        print(piv.reindex(index=MAIN, columns=transactions).round(2).to_string())
    if tx_eff:
        vmax = max(te.effect_log2.abs().max() for te in tx_eff.values())
        for n, te in tx_eff.items():
            fig_transaction_effects(te, n, vmax, transactions, out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--side", choices=sorted(SIDES), default="a",
                    help="workload whose ablation to analyse (default: a)")
    side = ap.parse_args().side
    run(pr.REPO, side, pr.REPO / "analysis" / "figures" / SIDES[side][1])


if __name__ == "__main__":
    main()
