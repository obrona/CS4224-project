"""Analyse the workload-A 2^5 factorial ablation (expt_a100 .. expt_a131).

Run from anywhere:  python3 analysis/ablation.py

Cells and factor levels come only from ablation/manifest.csv: expt_a<100+mask>
for mask 0..31 (bit0 T5R, bit1 T6R, bit2 T7R, bit3 DEL, bit4 RR) plus the
replicates expt_a2xx ("replicate of expt_a1xx"). Each cell is loaded with
plot_results.load_experiment, so its cross-checks and its validity rule
(pgbench exit code 0 and no aborted client) are the ones used everywhere else.
A cell without slurm-results/ has not been run yet.

Responses, per cell, valid points only:
  R_peak  highest TPS among the cell's valid client counts (and at which count)
  R_c     TPS at client count c
Effects are computed on log2 of the response and reported as ratios 2^effect.

Factorial effects (only once all 32 cells have data):
  31 contrasts per response: effect = mean(log2 y | +) - mean(log2 y | -), with
  +/- the product of the factors' +-1 levels. The 16 three-, four- and five-factor
  interactions are ASSUMED TO BE NOISE and pooled into the error estimate:
  SE = sqrt(mean of their squared effects), 16 df; 95% interval = effect +-
  t(0.975, 16) * SE. Lenth's pseudo standard error over all 31 effects is
  reported next to it as a cross-check. A response is estimated only when all
  32 cells are valid for it; otherwise the non-valid cells are listed. Nothing
  is imputed.

Output, all in analysis/figures/ablation/ (this script owns the directory's
*.png, *.pdf and *.csv): figures as PNG (dpi 200) + PDF, one chart per file, and
CSV tables. The module docstring of plot_results.py documents the palette; the
extra roles used here are the documented diverging pair (blue <-> red with the
neutral band grey midpoint) and the status "critical" red for non-valid points.
"""

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
FACTORS = [("t5_routing", "T5R"), ("t6_rollup", "T6R"), ("t7_routing", "T7R"),
           ("t1_delegation", "DEL"), ("repeatable_read", "RR")]
SHORT = [s for _, s in FACTORS]
K = len(FACTORS)
N_CELLS = 2 ** K
MANIFEST_COLUMNS = ["experiment", "mask"] + [f for f, _ in FACTORS] + ["source"]
CELL_OFFSET = 100            # factorial cell name: expt_a<100 + mask>
REPLICATE_OFFSET = 200       # replicate name: expt_a<200 + mask>
REPLICATE_SOURCE = re.compile(r"^replicate of (expt_a\d+)$")
ABLATION_NAME = re.compile(r"^expt_a(\d+)$")

# Every contrast, by order then lexicographic factor order.
EFFECTS = [combo for order in range(1, K + 1) for combo in combinations(range(K), order)]
POOL_MIN_ORDER = 3           # 3-, 4- and 5-factor interactions form the error pool
DF_POOLED = sum(1 for c in EFFECTS if len(c) >= POOL_MIN_ORDER)   # 16
T_975 = 2.120                # t(0.975, 16), for DF_POOLED = 16

# Transactions no factor touches (ablation/README.md: T2, T3, T4, T8, T9 are
# exactly expt_a100's in every cell); the replicate check compares their latency.
UNCHANGED_TX = ["T2", "T3", "T4", "T8", "T9"]
TX_EFFECT_CLIENTS = (1, 64)
REPLICATE_TOLERANCE = 0.02   # CLAUDE.md: unchanged transactions within ~2% at 1 client

SLOT1 = pr.CATEGORICAL[0]
DIV_LOW, DIV_MID, DIV_HIGH = pr.CATEGORICAL[7], pr.BAND, pr.CATEGORICAL[0]
CRITICAL = "#d03b3b"         # documented status "critical"; always paired with a label
POOL_NOTE = ("SE is pooled from the 16 three-, four- and five-factor interaction contrasts, "
             "which are assumed to be noise (16 df, t(0.975, 16) = 2.120).")


# ---- Manifest --------------------------------------------------------------
@dataclass(frozen=True)
class Cell:
    name: str                 # expt_a115
    index: int                # 115
    mask: int
    levels: tuple
    replicate_of: str | None  # id of the original cell, e.g. "a115"
    path: Path

    @property
    def id(self):
        return f"a{self.index}"

    @property
    def label(self):
        on = [SHORT[k] for k in range(K) if self.levels[k]]
        return "+".join(on) if on else "base"


def read_manifest(repo):
    """Factorial cells ordered by mask, and replicates; raises on any inconsistency."""
    path = repo / "ablation" / "manifest.csv"
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
        name_m = ABLATION_NAME.match(r.experiment)
        if not name_m:
            raise RuntimeError(f"{path}: experiment {r.experiment!r} is not expt_a<integer>")
        levels = tuple(int(getattr(r, f)) for f, _ in FACTORS)
        if any(v not in (0, 1) for v in levels):
            raise RuntimeError(f"{path}: {r.experiment} has factor levels {levels}, not 0/1")
        mask = int(r.mask)
        if mask != sum(v << k for k, v in enumerate(levels)):
            raise RuntimeError(f"{path}: {r.experiment} mask {mask} != factor levels {levels}")
        index = int(name_m.group(1))
        cell_path = repo / r.experiment
        if not cell_path.is_dir():
            raise FileNotFoundError(f"{path} lists {r.experiment}, but {cell_path} does not exist")
        rep = REPLICATE_SOURCE.match(r.source)
        if rep:
            if index != REPLICATE_OFFSET + mask:
                raise RuntimeError(f"{path}: replicate {r.experiment} should be named "
                                   f"expt_a{REPLICATE_OFFSET + mask} for mask {mask}")
            replicates.append((Cell(r.experiment, index, mask, levels, None, cell_path),
                               rep.group(1)))
        else:
            if index != CELL_OFFSET + mask:
                raise RuntimeError(f"{path}: {r.experiment} should be named "
                                   f"expt_a{CELL_OFFSET + mask} for mask {mask}")
            cells[mask] = Cell(r.experiment, index, mask, levels, None, cell_path)
    if sorted(cells) != list(range(N_CELLS)):
        raise RuntimeError(f"{path}: factorial masks {sorted(cells)} != 0..{N_CELLS - 1}")
    by_name = {c.name: c for c in cells.values()}
    reps = []
    for rc, orig in replicates:
        if orig not in by_name:
            raise RuntimeError(f"{path}: {rc.name} replicates {orig}, which is not a factorial cell")
        if by_name[orig].mask != rc.mask:
            raise RuntimeError(f"{path}: {rc.name} (mask {rc.mask}) replicates {orig} "
                               f"(mask {by_name[orig].mask})")
        reps.append(Cell(rc.name, rc.index, rc.mask, rc.levels, by_name[orig].id, rc.path))

    listed = set(m.experiment)
    stray = sorted(p.name for p in repo.iterdir()
                   if p.is_dir() and ABLATION_NAME.match(p.name)
                   and CELL_OFFSET <= int(ABLATION_NAME.match(p.name).group(1))
                   < REPLICATE_OFFSET + 100
                   and p.name not in listed)
    if stray:
        raise RuntimeError(f"{path} does not list ablation-range directories {stray}")
    return [cells[i] for i in range(N_CELLS)], sorted(reps, key=lambda c: c.index)


# ---- Loading and responses -------------------------------------------------
def load(cells):
    """(summary, tx, ids without data) for every cell that has slurm-results/."""
    summaries, txs, missing = [], [], []
    for c in cells:
        if not (c.path / "slurm-results").is_dir():
            missing.append(c.id)
            continue
        s, t = pr.load_experiment(pr.Experiment("a", c.index, c.path))
        for df in (s, t):
            df["mask"] = c.mask
            df["label"] = c.label
        summaries.append(s)
        txs.append(t)
    if not summaries:
        return None, None, missing
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
    return summary, tx, missing


def peak_of(summary, exp_id):
    """(R_peak, clients) over valid points, or (nan, nan) when the cell has none."""
    v = summary[(summary.exp == exp_id) & summary.valid]
    if v.empty:
        return np.nan, np.nan
    r = v.loc[v.overall_tps.idxmax()]
    return float(r.overall_tps), int(r.clients)


def tps_at(summary, exp_id, clients):
    """TPS at one client count if that point exists and is valid, else nan."""
    r = summary[(summary.exp == exp_id) & (summary.clients == clients)]
    if r.empty or not bool(r.valid.iloc[0]):
        return np.nan
    return float(r.overall_tps.iloc[0])


def point_state(summary, exp_id, clients):
    """'valid', 'not valid [exit, aborted]' or 'no data' for one cell x client count."""
    r = summary[(summary.exp == exp_id) & (summary.clients == clients)]
    if r.empty:
        return "no data"
    r = r.iloc[0]
    if r.valid:
        return "valid"
    return f"not valid [exit {r.pgbench_exit_code}, {r.aborted_clients} aborted]"


def cells_table(summary, all_cells, clients):
    rows = []
    loaded = set(summary.exp)
    for c in all_cells:
        row = {"experiment": c.name, "exp": c.id, "mask": c.mask, "label": c.label,
               "replicate_of": c.replicate_of or ""}
        row.update({f: c.levels[k] for k, (f, _) in enumerate(FACTORS)})
        row["has_data"] = c.id in loaded
        peak, at = peak_of(summary, c.id) if c.id in loaded else (np.nan, np.nan)
        row["r_peak_tps"] = peak
        row["r_peak_clients"] = at
        for n in clients:
            row[f"tps_c{n}"] = tps_at(summary, c.id, n) if c.id in loaded else np.nan
        rows.append(row)
    return pd.DataFrame(rows).astype({"r_peak_clients": "Int64"})


def validity_table(summary, all_cells, clients):
    rows = []
    loaded = set(summary.exp)
    for c in all_cells:
        for n in clients:
            r = summary[(summary.exp == c.id) & (summary.clients == n)]
            base = {"experiment": c.name, "exp": c.id, "mask": c.mask, "label": c.label,
                    "clients": n}
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
    cols = ["experiment", "exp", "mask", "label", "clients", "state", "overall_tps",
            "pgbench_exit_code", "aborted_clients", "failed_log_records",
            "serialization_failures", "deadlock_failures"]
    v = pd.DataFrame(rows).reindex(columns=cols)
    for col in cols[6:]:
        if col != "overall_tps":
            v[col] = v[col].astype("Int64")
    return v


# ---- Factorial effects -----------------------------------------------------
def effect_name(combo):
    return ":".join(SHORT[k] for k in combo)


def design():
    """32 x 5 matrix of +-1 factor levels, row = mask."""
    return np.array([[1 if (m >> k) & 1 else -1 for k in range(K)] for m in range(N_CELLS)])


def factorial_effects(y):
    """All 31 effects of log2 response y (length 32, indexed by mask) with error estimates."""
    X = design()
    rows = []
    for combo in EFFECTS:
        col = X[:, list(combo)].prod(axis=1)
        rows.append({"effect": effect_name(combo), "order": len(combo),
                     "effect_log2": float(col @ y) / (N_CELLS / 2)})
    df = pd.DataFrame(rows)
    df["in_error_pool"] = df.order >= POOL_MIN_ORDER
    se = math.sqrt(float((df.effect_log2[df.in_error_pool] ** 2).mean()))
    a = df.effect_log2.abs()
    s0 = 1.5 * a.median()
    pse = 1.5 * a[a < 2.5 * s0].median()
    df["ratio"] = 2 ** df.effect_log2
    df["se_log2"] = se
    df["ci95_low_ratio"] = 2 ** (df.effect_log2 - T_975 * se)
    df["ci95_high_ratio"] = 2 ** (df.effect_log2 + T_975 * se)
    df["t_pooled"] = df.effect_log2 / se
    df["lenth_pse_log2"] = pse
    df["effect_over_pse"] = df.effect_log2 / pse
    df["df_pooled"] = DF_POOLED
    df["t_quantile"] = T_975
    df.attrs.update(se=se, pse=pse, grand_mean_log2=float(np.mean(y)))
    return df


def response_vector(values, cells):
    """log2 of {exp id: value} ordered by mask; the caller guarantees all 32 are present."""
    return np.log2(np.array([values[c.id] for c in cells], dtype=float))


def not_estimable_note(summary, cells, clients):
    """Cells that block estimation at one client count, with their state."""
    out = []
    for c in cells:
        st = point_state(summary, c.id, clients)
        if st != "valid":
            out.append(f"{c.id} {st}")
    return out


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


# ---- Figures ---------------------------------------------------------------
def fig_main_effects_peak(eff, out):
    main = eff[eff.order == 1].reset_index(drop=True)
    width = 6.6
    fig, ax = plt.subplots(figsize=(width, 2.8))
    y = np.arange(K)[::-1]
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
    ax.set_ylim(-0.6, K - 0.4)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("ratio of peak TPS, factor ON / OFF (log scale)")
    ax.set_title("Main effects on peak throughput over 32 cells, with 95% intervals", loc="left")
    pr.caption(ax, [
        "Effect = mean log2 R_peak of the 16 cells with the factor ON minus the 16 with it "
        "OFF, shown as 2^effect. R_peak = highest TPS among a cell's valid client counts "
        "(peak client count differs by cell; see cells.csv). Interval = effect ± 2.120 × SE. "
        + POOL_NOTE,
        f"SE = {eff.attrs['se']:.4f} log2; Lenth PSE over all 31 effects = "
        f"{eff.attrs['pse']:.4f} log2.",
    ], width)
    pr.save(fig, out, "main_effects_peak")


def fig_interactions_peak(eff, out):
    two = eff[eff.order == 2].set_index("effect")
    vmax = eff.effect_log2.abs().max()
    norm = Normalize(-vmax, vmax)
    cmap = diverging_cmap()
    # Lower triangle of the 5 x 5 factor matrix; its diagonal and the T5R row and
    # RR column hold nothing, so rows are T6R..RR and columns T5R..DEL.
    n = K - 1
    g = np.full((n, n), np.nan)
    for i in range(n):
        for j in range(i + 1):
            g[i, j] = two.loc[effect_name((j, i + 1)), "effect_log2"]
    width = 5.4
    fig, ax = plt.subplots(figsize=(width, 4.2))
    im = ax.imshow(np.ma.masked_invalid(g), cmap=cmap, norm=norm, aspect="equal")
    for i in range(n):
        for j in range(i + 1):
            r = two.loc[effect_name((j, i + 1))]
            fill = to_hex(cmap(norm(g[i, j])))
            ink = pr.ink_for(fill)
            ax.text(j, i - 0.12, fmt_ratio(r.ratio), ha="center", va="center", fontsize=8,
                    color=ink)
            ax.text(j, i + 0.2, fmt_ci(r.ci95_low_ratio, r.ci95_high_ratio), ha="center",
                    va="center", fontsize=6, color=ink)
    ax.set_xticks(range(n), SHORT[:-1])
    ax.set_yticks(range(n), SHORT[1:])
    ax.tick_params(length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("Two-factor interactions on peak throughput over 32 cells", loc="left")
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cb.outline.set_visible(False)
    pos, labels = ratio_tick_values(-vmax, vmax, max_ticks=7)
    cb.set_ticks(pos, labels=labels)
    cb.set_label("interaction ratio (log scale)", color=pr.INK_2)
    pr.caption(ax, [
        "Cell (row, column) = interaction of the two factors: half the difference between "
        "the column factor's log2 effect with the row factor ON and with it OFF, shown as "
        "2^effect, with its 95% interval. Blue: the pair together gives more peak TPS than "
        "the two main effects predict; red: less. The colour scale spans the largest of "
        "all 31 effects, so interactions and main effects share one scale. " + POOL_NOTE,
    ], width, offset_pt=14)
    pr.save(fig, out, "interactions_peak")


def fig_half_normal_peak(eff, out):
    d = eff.assign(abs_e=eff.effect_log2.abs()).sort_values("abs_e").reset_index(drop=True)
    m = len(d)
    d["q"] = [normal_quantile(0.5 + 0.5 * (i + 0.5) / m) for i in range(m)]
    se = eff.attrs["se"]
    d["beyond"] = d.abs_e > T_975 * se
    width = 6.6
    fig, ax = plt.subplots(figsize=(width, 8.2))
    fig.subplots_adjust(top=0.95, bottom=0.14)
    xmax = d.abs_e.max()
    xlo, xhi = -0.04 * xmax, 1.06 * xmax
    qmax = d.q.max() * 1.03
    ax.plot([0, qmax * se], [0, qmax], color=pr.INK_2, lw=1, zorder=1)
    for pool in (False, True):
        for beyond in (False, True):
            p = d[(d.in_error_pool == pool) & (d.beyond == beyond)]
            c = SLOT1 if beyond else pr.MUTED
            if pool:
                ax.scatter(p.abs_e, p.q, s=34, facecolor=pr.SURFACE, edgecolor=c,
                           linewidth=1.4, zorder=3)
            else:
                ax.scatter(p.abs_e, p.q, s=34, color=c, edgecolor=pr.SURFACE,
                           linewidth=1.2, zorder=3)
    texts = []
    mid = (xlo + xhi) / 2
    for r in d.itertuples():
        right = r.abs_e < mid
        texts.append(ax.annotate(f"{r.effect} {fmt_ratio(r.ratio)}", xy=(r.abs_e, r.q),
                                 xytext=(6 if right else -6, 0), textcoords="offset points",
                                 ha="left" if right else "right", va="center", fontsize=6.3,
                                 color=pr.INK_2))
    ax.set_xlim(xlo, xhi)
    ax.set_ylim(0, qmax)
    ratio_ticks(ax, "x", xlo, xhi)
    ax.set_xlabel("|effect| on peak TPS, as the ratio 2^|effect| (log2 spacing)")
    ax.set_ylabel("half-normal quantile")
    ax.set_title("Half-normal plot of all 31 effects on peak throughput", loc="left")
    handles = [
        Line2D([], [], ls="", marker="o", ms=5.5, color=SLOT1, mec=pr.SURFACE,
               label="95% interval excludes ×1"),
        Line2D([], [], ls="", marker="o", ms=5.5, color=pr.MUTED, mec=pr.SURFACE,
               label="95% interval includes ×1"),
        Line2D([], [], ls="", marker="o", ms=5.5, mfc=pr.SURFACE, mec=pr.INK_2, mew=1.3,
               label="hollow: 3- to 5-factor, in the error pool"),
        Line2D([], [], color=pr.INK_2, lw=1, label="|effect| = SE × quantile"),
    ]
    ax.legend(handles=handles, loc="lower right")
    pr.caption(ax, [
        "Each label gives the signed effect as a ratio (ON / OFF for main effects). "
        f"SE = {se:.4f} log2, Lenth PSE = {eff.attrs['pse']:.4f} log2. Effects on the line "
        "behave like noise of that size; effects far right of it do not. " + POOL_NOTE,
    ], width)
    pr.check_labels_disjoint(fig, texts)
    pr.save(fig, out, "half_normal_peak")


def fig_main_effects_by_clients(by_c, skipped, out):
    clients = sorted(by_c)
    width = 7.2
    fig, ax = plt.subplots(figsize=(width, 4.2))
    fig.subplots_adjust(right=0.74)
    ax.axhline(0, color=pr.INK_2, lw=0.8, zorder=1)
    ends, allv = [], []
    for k, s in enumerate(SHORT):
        dodge = (k - (K - 1) / 2) * 0.06
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
    ax.set_ylabel("ratio of TPS, factor ON / OFF (log scale)")
    ax.set_title("Main effects on throughput at each client count with all 32 cells valid",
                 loc="left")
    pr.label_line_ends(ax, ends)
    pr.check_labels_disjoint(fig, list(ax.texts))
    handles = [Line2D([], [], color=pr.CATEGORICAL[k], marker="o", ms=5, mec=pr.SURFACE,
                      label=s) for k, s in enumerate(SHORT)]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.12, 1.0))
    pr.caption(ax, [
        "Effect per client count c = mean log2 TPS at c of the 16 cells with the factor ON "
        "minus the 16 with it OFF; vertical bars are 95% intervals (effect ± 2.120 × SE at "
        "that c); points are offset sideways per factor so the bars do not overlap. " + POOL_NOTE,
        ("Not estimated (a cell is not valid or has no point there): "
         + "; ".join(f"{c} clients: {', '.join(v)}" for c, v in skipped.items()) + ".")
        if skipped else "",
    ], width)
    pr.save(fig, out, "main_effects_by_clients")


def fig_ratio_bars(tab, missing, title, ylabel_fmt, note, out, name):
    """Horizontal bars of R_peak ratio per factor from a ×1 baseline (one series)."""
    width = 6.6
    fig, ax = plt.subplots(figsize=(width, 2.9))
    y = np.arange(K)[::-1]
    have = tab.set_index("factor")
    vals = [math.log2(have.loc[s, "ratio"]) if s in have.index and pd.notna(have.loc[s, "ratio"])
            else np.nan for s in SHORT]
    finite = [v for v in vals if not np.isnan(v)] or [0.0]   # every pair lacks a valid peak
    lo, hi = min(min(finite), 0.0), max(max(finite), 0.0)
    span = max(hi - lo, 0.1)
    # Room on each side for the "no data" text and the tip labels.
    xlo, xhi = lo - (0.2 if lo < 0 else 0.05) * span, hi + (0.2 if hi > 0 else 0.05) * span
    if hi <= 0:
        xhi += 0.25 * span                            # "no data" text runs right of ×1
    ratio_ticks(ax, "x", xlo, xhi)
    ax.axvline(0, color=pr.INK_2, lw=0.8, zorder=3)
    labels = []
    for yi, s, v in zip(y, SHORT, vals):
        if s in have.index:
            r = have.loc[s]
            labels.append(ylabel_fmt.format(factor=s, cell=r.cell, ref=r.reference))
        else:
            labels.append(s)
        if np.isnan(v):
            ax.text(0, yi, "  no data" if s not in have.index else "  no valid point",
                    va="center", ha="left", fontsize=7, color=pr.MUTED)
            continue
        ax.barh(yi, v, height=0.5, color=SLOT1, zorder=2)
        ax.annotate(fmt_ratio(2 ** v), xy=(v, yi), xytext=(4 if v >= 0 else -4, 0),
                    textcoords="offset points", ha="left" if v >= 0 else "right",
                    va="center", fontsize=7.5, color=pr.INK_2)
    ax.set_yticks(y, labels)
    ax.set_ylim(-0.6, K - 0.4)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("ratio of R_peak (log scale)")
    ax.set_title(title, loc="left")
    pr.caption(ax, [note, f"Not yet run: {', '.join(missing)}." if missing else ""], width)
    pr.save(fig, out, name)


def fig_peak_tps_by_cell(cells_df, out):
    d = cells_df[cells_df.has_data].copy()
    d["name"] = [f"{r.label}  {r.exp}" + (" (replicate)" if r.replicate_of else "")
                 for r in d.itertuples()]
    d = d.sort_values("r_peak_tps", ascending=False, na_position="last").reset_index(drop=True)
    n = len(d)
    width = 7.0
    fig, ax = plt.subplots(figsize=(width, 1.4 + 0.24 * n))
    y = np.arange(n)[::-1]
    xmax = d.r_peak_tps.max()
    for yi, r in zip(y, d.itertuples()):
        if pd.isna(r.r_peak_tps):
            ax.text(0, yi, " no valid point", va="center", fontsize=7, color=pr.MUTED)
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
        "R_peak = highest TPS among a cell's valid client counts; the value label gives it "
        "and the client count where it occurs. Labels list the factors ON (base = none).",
        f"Not yet run: {', '.join(missing)}." if missing else "",
    ], width)
    pr.save(fig, out, "peak_tps_by_cell")


def fig_validity_map(vt, all_cells, clients, out):
    rows = [c.id for c in all_cells]
    labels = [f"{c.id}  {c.label}" for c in all_cells]
    n, m = len(rows), len(clients)
    width = 1.9 + 0.95 * m
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
        index=SHORT, columns=transactions).to_numpy(dtype=float)
    norm = Normalize(-vmax, vmax)
    cmap = diverging_cmap(reverse=True)       # lower latency (ratio < 1) is blue
    width = 1.6 + 0.66 * len(transactions)
    fig, ax = plt.subplots(figsize=(width, 3.0))
    im = ax.imshow(g, cmap=cmap, norm=norm, aspect="auto")
    for i in range(K):
        for j in range(len(transactions)):
            fill = to_hex(cmap(norm(g[i, j])))
            ax.text(j, i, fmt_ratio(2 ** g[i, j]), ha="center", va="center", fontsize=7,
                    color=pr.ink_for(fill))
    ax.set_xticks(range(len(transactions)), transactions)
    ax.set_yticks(range(K), SHORT)
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
        f"Ratio = 2^(mean log2 avg_latency_ms of the 16 cells with the factor ON minus the 16 "
        f"with it OFF), all 32 cells valid at {pr.clients_label(clients)}. Blue = lower latency "
        "with the factor ON, red = higher. Colour scale shared by every transaction-effect "
        "heatmap. Intervals are in the CSV of the same name.",
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
             "one of the two is not valid there."]
    for p in pairs:
        d = lat1[lat1.pair == p]
        if not d.empty:
            parts.append(f"{p} avg latency ratio at 1 client, transactions no factor changes: "
                         + ", ".join(f"{r.transaction} {fmt_ratio(r.ratio)}"
                                     for r in d.itertuples() if pd.notna(r.ratio)) + ".")
    pr.caption(ax, parts, width)
    pr.save(fig, out, "replicate_check")


# ---- Pairwise comparisons --------------------------------------------------
def pair_rows(summary, cell, ref, factor, clients):
    """R_peak and R_c ratio rows for one cell against one reference cell."""
    rows = []
    pc, pcn = peak_of(summary, cell.id)
    pr_, prn = peak_of(summary, ref.id)
    rows.append({"factor": factor, "cell": cell.id, "reference": ref.id, "response": "r_peak",
                 "clients_cell": pcn, "clients_reference": prn, "tps_cell": pc,
                 "tps_reference": pr_, "ratio": pc / pr_})
    for n in clients:
        a, b = tps_at(summary, cell.id, n), tps_at(summary, ref.id, n)
        rows.append({"factor": factor, "cell": cell.id, "reference": ref.id,
                     "response": f"tps_c{n}", "clients_cell": n, "clients_reference": n,
                     "tps_cell": a, "tps_reference": b, "ratio": a / b})
    return rows


def compare(summary, cells, loaded, clients, ref_mask, pair_mask):
    """Rows for (cell, reference) = pair_mask(k), ref_mask per factor k; skips missing cells."""
    rows, missing = [], []
    for k, s in enumerate(SHORT):
        a, b = cells[pair_mask(k)], cells[ref_mask(k)]
        gone = [c.id for c in (a, b) if c.id not in loaded]
        if gone:
            missing += [g for g in gone if g not in missing]
            continue
        rows += pair_rows(summary, a, b, s, clients)
    df = pd.DataFrame(rows, columns=["factor", "cell", "reference", "response", "clients_cell",
                                     "clients_reference", "tps_cell", "tps_reference", "ratio"])
    return df.astype({"clients_cell": "Int64", "clients_reference": "Int64"}), missing


def replicate_tables(summary, tx, replicates, loaded, clients):
    rows, lat = [], []
    skipped = []
    for rc in replicates:
        orig = rc.replicate_of
        if rc.id not in loaded or orig not in loaded:
            skipped.append(f"{rc.id} / {orig}")
            continue
        pair = f"{rc.id} / {orig}"
        for n in clients:
            a, b = tps_at(summary, rc.id, n), tps_at(summary, orig, n)
            rows.append({"pair": pair, "metric": "overall_tps", "transaction": "",
                         "clients": n, "original": b, "replicate": a, "ratio": a / b})
        for t in UNCHANGED_TX:
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
    return pd.DataFrame(rows, columns=cols), pd.DataFrame(lat, columns=cols), skipped


# ---- Driver ----------------------------------------------------------------
def print_effects(title, eff):
    print(f"\n{title}  (geometric mean {2 ** eff.attrs['grand_mean_log2']:.1f}; "
          f"SE {eff.attrs['se']:.4f} log2 pooled from 16 higher-order contrasts assumed noise; "
          f"Lenth PSE {eff.attrs['pse']:.4f} log2)")
    show = eff[eff.order <= 2]
    for r in show.itertuples():
        flag = "" if r.ci95_low_ratio <= 1 <= r.ci95_high_ratio else "  *"
        print(f"  {r.effect:<9} {fmt_ratio(r.ratio)}  95% {fmt_ci(r.ci95_low_ratio, r.ci95_high_ratio)}"
              f"  t={r.t_pooled:6.2f}  e/PSE={r.effect_over_pse:6.2f}{flag}")


def run(repo, out):
    start = time.perf_counter()
    cells, replicates = read_manifest(repo)
    all_cells = cells + replicates
    out.mkdir(parents=True, exist_ok=True)
    # This script owns the directory: drop last run's outputs so a table or
    # figure that is no longer estimable does not survive as a stale file.
    for pattern in ("*.png", "*.pdf", "*.csv"):
        for f in out.glob(pattern):
            f.unlink()

    summary, tx, missing_all = load(all_cells)
    if summary is None:
        print(f"no ablation cell has slurm-results/ yet under {repo}; nothing to analyse")
        return []
    loaded = set(summary.exp)
    clients = sorted(summary.clients.unique())
    transactions = sorted(tx.transaction.unique(), key=pr.tx_key)
    missing = [c.id for c in cells if c.id not in loaded]
    print(f"{len(loaded)} of {len(all_cells)} manifest entries have results; "
          f"client counts {clients}")

    cells_df = cells_table(summary, all_cells, clients)
    cells_df.to_csv(out / "cells.csv", index=False)
    vt = validity_table(summary, all_cells, clients)
    vt.to_csv(out / "validity.csv", index=False)
    fig_validity_map(vt, all_cells, clients, out)
    fig_peak_tps_by_cell(cells_df, out)

    by_mask = {c.mask: c for c in cells}
    full = N_CELLS - 1
    add_one, miss_a = compare(summary, by_mask, loaded, clients, lambda k: 0, lambda k: 1 << k)
    loo, miss_l = compare(summary, by_mask, loaded, clients, lambda k: full ^ (1 << k),
                          lambda k: full)
    add_one.to_csv(out / "add_one.csv", index=False)
    loo.to_csv(out / "leave_one_out.csv", index=False)
    if not add_one.empty:
        fig_ratio_bars(add_one[add_one.response == "r_peak"], miss_a,
                       "Peak throughput of each single-factor cell relative to the base cell",
                       "{factor}  ({cell} / {ref})",
                       "Ratio = R_peak of the cell with only that factor ON / R_peak of a100 "
                       "(no factor ON). R_peak = highest TPS among a cell's valid client counts; "
                       "the two peaks may sit at different client counts (add_one.csv).",
                       out, "add_one_peak")
    else:
        print(f"add-one: skipped, no pair has both cells yet (missing {', '.join(miss_a)})")
    if not loo.empty:
        fig_ratio_bars(loo[loo.response == "r_peak"], miss_l,
                       "Peak throughput of the all-factor cell relative to each cell missing one",
                       "{factor}  ({cell} / {ref})",
                       "Ratio = R_peak of a131 (every factor ON) / R_peak of the cell with only "
                       "that factor OFF. R_peak = highest TPS among a cell's valid client "
                       "counts (leave_one_out.csv).", out, "leave_one_out_peak")
    else:
        print(f"leave-one-out: skipped, no pair has both cells yet (missing {', '.join(miss_l)})")
    if miss_a or miss_l:
        print(f"add-one / leave-one-out: pairs without results skipped "
              f"(missing {', '.join(dict.fromkeys(miss_a + miss_l))})")

    rep, lat1, rep_skipped = replicate_tables(summary, tx, replicates, loaded, clients)
    rep.to_csv(out / "replicates.csv", index=False)
    if not rep.empty:
        fig_replicate_check(rep, lat1, out)
        print("\nreplicates (ratio replicate / original):")
        for p, g in rep.groupby("pair", sort=False):
            t = g[g.metric == "overall_tps"]
            lt = g[g.metric == "avg_latency_ms"]
            print(f"  {p} TPS:  " + "  ".join(f"c{r.clients} {fmt_ratio(r.ratio)}"
                                              for r in t.itertuples()))
            print(f"  {p} avg latency c1:  " + "  ".join(f"{r.transaction} {fmt_ratio(r.ratio)}"
                                                         for r in lt.itertuples()))
    if rep_skipped:
        print(f"replicate check: skipped {', '.join(rep_skipped)} (a run has no results yet)")

    if missing:
        print(f"effects: skipped, {len(missing)} of {N_CELLS} cells have no results yet: "
              f"{', '.join(missing)}")
    else:
        effects_step(summary, tx, cells, clients, transactions, out)

    names = sorted(p.name for p in out.iterdir() if p.suffix in (".png", ".csv"))
    print(f"\nwrote to {out} in {time.perf_counter() - start:.1f}s:\n  " + " ".join(names))
    return names


def effects_step(summary, tx, cells, clients, transactions, out):
    no_peak = [c.id for c in cells if np.isnan(peak_of(summary, c.id)[0])]
    if no_peak:
        print(f"effects on R_peak: not estimated, no valid point at all in {', '.join(no_peak)}")
    else:
        peaks = {c.id: peak_of(summary, c.id)[0] for c in cells}
        eff = factorial_effects(response_vector(peaks, cells))
        eff.insert(0, "response", "r_peak")
        eff.to_csv(out / "effects_peak.csv", index=False)
        print_effects("effects on R_peak", eff)
        fig_main_effects_peak(eff, out)
        fig_interactions_peak(eff, out)
        fig_half_normal_peak(eff, out)

    by_c, skipped = {}, {}
    for n in clients:
        blockers = not_estimable_note(summary, cells, n)
        if blockers:
            skipped[n] = blockers
            print(f"effects at {n} clients: not estimated; {'; '.join(blockers)}")
            continue
        vals = {c.id: tps_at(summary, c.id, n) for c in cells}
        eff = factorial_effects(response_vector(vals, cells))
        eff.insert(0, "response", f"tps_c{n}")
        eff.to_csv(out / f"effects_c{n}.csv", index=False)
        by_c[n] = eff
        print_effects(f"effects on TPS at {n} clients", eff)
    if by_c:
        fig_main_effects_by_clients(by_c, skipped, out)
    else:
        print("main effects by client count: no client count has all 32 cells valid")

    tx_eff = {}
    for n in TX_EFFECT_CLIENTS:
        if n in skipped or n not in clients:
            print(f"transaction effects at {n} clients: not estimated "
                  f"({'; '.join(skipped.get(n, ['client count not run']))})")
            continue
        rows = []
        for t in transactions:
            d = tx[(tx.clients == n) & (tx.transaction == t)].set_index("exp").avg_latency_ms
            eff = factorial_effects(response_vector(d.to_dict(), cells))
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
        print(piv.reindex(index=SHORT, columns=transactions).round(2).to_string())
    if tx_eff:
        vmax = max(te.effect_log2.abs().max() for te in tx_eff.values())
        for n, te in tx_eff.items():
            fig_transaction_effects(te, n, vmax, transactions, out)


def main():
    run(pr.REPO, pr.REPO / "analysis" / "figures" / "ablation")


if __name__ == "__main__":
    main()
