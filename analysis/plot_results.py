"""Plot every benchmarked experiment of every workload.

Run from anywhere:  python3 analysis/plot_results.py

Discovery: an experiment is a repo-root directory named expt_<letter><integer>
(expt_a0, expt_b12). The letter is the workload; experiments are ordered by the
integer. An experiment without slurm-results/ has not been run yet and is skipped
with one printed line. An experiment with slurm-results/ must hold exactly one
job-*/benchmark-results/ containing summary.csv and transaction_metrics.csv.
Client counts and transaction ids are read from those CSVs.

Output, per workload <w>, in analysis/figures/<w>/ as PNG (dpi 200) and PDF, one
chart per file:
  throughput                    throughput vs clients, one line per experiment
  latency_p50 / _p95 / _p99     overall latency percentile vs clients
  latency_share_c<N>            share of total measured latency per transaction
  heatmap_avg_c<N>              average latency, experiment x transaction
  heatmap_p99_c<N>              p99 latency, experiment x transaction
plus one analysis/figures/validity.csv covering all workloads.

A point is not valid when pgbench_exit_code != 0 or at least one client aborted
(counted from result-c<N>.txt). Invalid points are drawn with hollow markers
(line charts) or hatched rows (bar charts, heatmaps) and named in the caption.

Colour rules (dataviz method, light mode, white print surface #ffffff):
  * <= 8 experiments in a workload: the eight categorical slots in fixed order,
    so an experiment keeps its colour in every figure of that workload.
    validate_palette.js on all eight slots, adjacent pairs: every gate passes;
    aqua/yellow/magenta sit below 3:1 contrast, so the numbers are also in
    tables (validity.csv and the source CSVs).
  * > 8 experiments: no generated categorical hues. Experiments take an ordinal
    blue ramp by index (documented steps 250..700; interpolated between them
    only when more than 10 experiments exist), and every line is labelled
    directly at its end and in the legend. The ramp necessarily fails the
    validator's adjacent-step dL >= 0.06 check beyond 8 steps (monotone, single
    hue and light-end contrast pass); that is why identity is carried by the
    direct labels, never by hue alone.
  * transactions in latency_share take categorical slots in id order; a
    transaction that never reaches FOLD_BELOW_PCT of the latency in any run of
    that workload folds into a grey "Other" (as does any beyond 8 slots).
  * heatmap magnitudes use the single-hue blue sequential ramp.
"""

import re
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import patheffects  # noqa: E402
from matplotlib.text import Text  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, LogNorm, to_hex  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

EXPT_DIR = re.compile(r"^expt_([a-z])(\d+)$")
TX_ID = re.compile(r"^T(\d+)$")

SUMMARY_COLUMNS = ["clients", "successful_transactions", "failed_log_records", "overall_tps",
                   "overall_median_latency_ms", "overall_p95_latency_ms",
                   "overall_p99_latency_ms", "serialization_failures", "deadlock_failures",
                   "pgbench_exit_code"]
TX_COLUMNS = ["clients", "transaction", "successful_transactions", "avg_latency_ms",
              "p99_latency_ms"]

FOLD_BELOW_PCT = 5.0          # latency_share: fold transactions that never reach this share
SEGMENT_LABEL_MIN_PCT = 12.0  # latency_share: print the value only on segments this wide

# ---- Palette (documented reference instance, light mode) -------------------
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
               "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER_COLOR = "#c3c2b7"
BLUE_RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
             "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281",
             "#0d366b"]
# Ordinal use starts at step 250: lighter steps fall below 2:1 on the surface.
ORDINAL_RAMP = BLUE_RAMP[3:]

SURFACE = "#ffffff"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BAND = "#f0efec"

INVALID_RULE = "pgbench exit code != 0 or at least one client aborted"
HATCH = "//"                  # marks invalid rows; sparse so value labels stay legible

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 9,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8,
    "axes.labelcolor": INK_2,
    "axes.titlecolor": INK,
    "axes.titlesize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "grid.linestyle": "-",
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK_2,
    "ytick.labelcolor": INK_2,
    "legend.frameon": False,
    "legend.fontsize": 8,
    "lines.linewidth": 1.5,
    "lines.solid_capstyle": "round",
    "lines.solid_joinstyle": "round",
    "hatch.color": INK_2,
    "hatch.linewidth": 0.6,
})


# ---- Discovery -------------------------------------------------------------
@dataclass(frozen=True)
class Experiment:
    workload: str
    index: int
    path: Path

    @property
    def id(self):
        return f"{self.workload}{self.index}"


def discover(repo):
    """Experiments with data, grouped by workload and ordered by index."""
    found = {}
    for p in sorted(repo.iterdir()):
        m = EXPT_DIR.match(p.name)
        if not (m and p.is_dir()):
            continue
        exp = Experiment(m.group(1), int(m.group(2)), p)
        if not (p / "slurm-results").is_dir():
            print(f"skip {p.name}: no slurm-results/ (not run yet)")
            continue
        if exp.id in found:
            raise RuntimeError(f"{p} and {found[exp.id].path} both map to experiment {exp.id}")
        found[exp.id] = exp
    if not found:
        raise RuntimeError(f"no expt_<letter><integer>/slurm-results/ under {repo}")
    by_workload = {}
    for exp in sorted(found.values(), key=lambda e: (e.workload, e.index)):
        by_workload.setdefault(exp.workload, []).append(exp)
    return by_workload


def results_dir(exp):
    """The single benchmark-results directory of one experiment."""
    slurm = exp.path / "slurm-results"
    jobs = sorted(p for p in slurm.glob("job-*") if p.is_dir())
    if len(jobs) != 1:
        raise RuntimeError(f"expected exactly one job-* directory in {slurm}, "
                           f"found {len(jobs)}: {[p.name for p in jobs]}")
    d = jobs[0] / "benchmark-results"
    if not d.is_dir():
        raise FileNotFoundError(f"missing results directory: {d}")
    return d


# ---- Loading ---------------------------------------------------------------
def read_csv_checked(path, columns):
    if not path.is_file():
        raise FileNotFoundError(f"missing results file: {path}")
    df = pd.read_csv(path)
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise RuntimeError(f"{path}: missing columns {missing}")
    if df.empty:
        raise RuntimeError(f"{path}: no rows")
    return df


def count_aborted_clients(path):
    """Number of distinct pgbench clients that aborted during the measured run."""
    if not path.is_file():
        raise FileNotFoundError(f"missing results file: {path}")
    return len(set(re.findall(r"client (\d+) script \d+ aborted", path.read_text())))


def tx_key(t):
    m = TX_ID.match(t)
    if not m:
        raise RuntimeError(f"transaction id {t!r} does not match T<integer>")
    return int(m.group(1))


def load_experiment(exp):
    d = results_dir(exp)
    s_path, t_path = d / "summary.csv", d / "transaction_metrics.csv"
    s = read_csv_checked(s_path, SUMMARY_COLUMNS)
    t = read_csv_checked(t_path, TX_COLUMNS)

    if s.clients.duplicated().any():
        raise RuntimeError(f"{s_path}: duplicate client counts {sorted(s.clients)}")
    clients = sorted(s.clients)
    if sorted(t.clients.unique()) != clients:
        raise RuntimeError(f"{t_path}: client counts {sorted(t.clients.unique())} "
                           f"!= summary.csv {clients}")
    transactions = sorted(t.transaction.unique(), key=tx_key)
    if t.duplicated(["clients", "transaction"]).any():
        raise RuntimeError(f"{t_path}: duplicate (clients, transaction) rows")
    if len(t) != len(clients) * len(transactions):
        raise RuntimeError(f"{t_path}: {len(t)} rows, expected {len(clients)} clients x "
                           f"{len(transactions)} transactions = "
                           f"{len(clients) * len(transactions)}")
    per_client = t.groupby("clients").successful_transactions.sum()
    overall = s.set_index("clients").successful_transactions
    off = per_client[per_client != overall.loc[per_client.index]]
    if not off.empty:
        raise RuntimeError(f"{t_path}: per-transaction successful_transactions sum "
                           f"{off.to_dict()} != summary.csv {overall.loc[off.index].to_dict()}")

    s["aborted_clients"] = [count_aborted_clients(d / f"result-c{c}.txt") for c in s.clients]
    s["valid"] = (s.pgbench_exit_code == 0) & (s.aborted_clients == 0)
    for df in (s, t):
        df["workload"] = exp.workload
        df["exp"] = exp.id
        df["exp_index"] = exp.index
    t = t.merge(s[["clients", "valid"]], on="clients")
    return s, t


def load_workload(exps):
    loaded = [load_experiment(e) for e in exps]
    summary = pd.concat([s for s, _ in loaded], ignore_index=True)
    tx = pd.concat([t for _, t in loaded], ignore_index=True)
    return summary, tx


# ---- Helpers ---------------------------------------------------------------
def save(fig, out, name):
    for ext in ("png", "pdf"):
        fig.savefig(out / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def ink_for(hex_color):
    """White or ink text on a filled cell: whichever has the higher WCAG contrast."""
    def rel_lum(h):
        ch = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        ch = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    fill = rel_lum(hex_color)
    vs_white = 1.05 / (fill + 0.05)
    vs_ink = (fill + 0.05) / (rel_lum(INK) + 0.05)
    return INK if vs_ink >= vs_white else "#ffffff"


def fmt_ms(v):
    if v >= 9_950:              # would print as "10.0k"
        return f"{v / 1000:.0f}k"
    if v >= 1_000:
        return f"{v / 1000:.1f}k"
    if v >= 100:
        return f"{v:.0f}"
    if v >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}"


def clients_label(c):
    return f"{c} client{'s' if c != 1 else ''}"


def experiment_colors(exp_ids):
    """Colour per experiment id; ordinal ramp (and direct labels) past 8 experiments."""
    n = len(exp_ids)
    if n <= len(CATEGORICAL):
        return dict(zip(exp_ids, CATEGORICAL))
    if n <= len(ORDINAL_RAMP):
        idx = np.round(np.linspace(0, len(ORDINAL_RAMP) - 1, n)).astype(int)
        return {e: ORDINAL_RAMP[i] for e, i in zip(exp_ids, idx)}
    # More experiments than documented ordinal steps: interpolate between them.
    # Order is still readable; identity comes from the direct labels.
    cmap = LinearSegmentedColormap.from_list("ordinal", ORDINAL_RAMP)
    return {e: to_hex(cmap(x)) for e, x in zip(exp_ids, np.linspace(0, 1, n))}


def caption(ax, parts, width_in, offset_pt=34):
    """Factual caption below an axes; offset in points so it clears the x label."""
    chars = int(width_in * 18)
    text = "\n".join(textwrap.fill(p, chars) for p in parts if p)
    if text:
        ax.annotate(text, xy=(0, 0), xycoords="axes fraction", xytext=(0, -offset_pt),
                    textcoords="offset points", ha="left", va="top", fontsize=7,
                    color=INK_2)


def invalid_note(summary, lead):
    """Names every invalid point in `summary` as '<exp> <clients> [exit, aborted]'."""
    bad = summary[~summary.valid].sort_values(["exp_index", "clients"])
    if bad.empty:
        return ""
    runs = []
    for _, g in bad.groupby("exp_index", sort=True):
        # Non-breaking spaces keep one point (and its experiment id) on one line.
        pts = ", ".join(f"{r.clients}\u00a0[{r.pgbench_exit_code},\u00a0{r.aborted_clients}]"
                        for r in g.itertuples())
        runs.append(f"{g.exp.iloc[0]}\u00a0{pts}")
    return (f"{lead} not valid ({INVALID_RULE}); listed as experiment, clients "
            f"[exit code, aborted\u00a0clients]: " + "; ".join(runs) + ".")


def missing_clients_note(summary, exp_ids, all_clients):
    parts = []
    for e in exp_ids:
        have = set(summary.loc[summary.exp == e, "clients"])
        gone = [c for c in all_clients if c not in have]
        if gone:
            parts.append(f"{e} at {', '.join(map(str, gone))} clients")
    return f"No data: {'; '.join(parts)}." if parts else ""


def halo(fill):
    """Stroke in the cell's own fill, so hatching never runs through a value label."""
    return [patheffects.withStroke(linewidth=2.5, foreground=fill)]


def label_line_ends(ax, ends, fontsize=7.5):
    """Label each line in a column right of the axes, nudged apart, with a leader.

    ends: list of (label, x, y, color) at each line's last point, in data coords.
    """
    fig = ax.figure
    # Freeze autoscaled limits first: transData is stale until they are resolved.
    ax.set_xlim(ax.get_xlim())
    ax.set_ylim(ax.get_ylim())
    to_axes = ax.transData + ax.transAxes.inverted()
    ys = np.array([to_axes.transform((x, y))[1] for _, x, y, _ in ends])
    order = np.argsort(ys)
    ax_h_pt = ax.get_position().height * fig.get_figheight() * 72
    gap = fontsize * 1.6 / ax_h_pt          # text box height plus a little air
    placed = ys[order].copy()
    # Push up to clear neighbours, pull the top back under the axes top, then push
    # up once more: labels stay disjoint, exceeding the axes only if they cannot fit.
    for i in range(1, len(placed)):
        placed[i] = max(placed[i], placed[i - 1] + gap)
    placed[-1] = min(placed[-1], 1.0)
    for i in range(len(placed) - 2, -1, -1):
        placed[i] = min(placed[i], placed[i + 1] - gap)
    for i in range(1, len(placed)):
        placed[i] = max(placed[i], placed[i - 1] + gap)
    for k, i in enumerate(order):
        label, x, y, color = ends[i]
        ax.annotate(label, xy=(x, y), xycoords="data", xytext=(1.06, placed[k]),
                    textcoords="axes fraction", ha="left", va="center", fontsize=fontsize,
                    color=INK_2, annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=color, lw=0.8,
                                    shrinkA=0, shrinkB=3))


def check_labels_disjoint(fig, texts):
    """Raise if any two rendered labels overlap (layout check for direct labels)."""
    fig.canvas.draw()
    # Text's own extent: Annotation.get_window_extent would include the leader line.
    boxes = [Text.get_window_extent(t) for t in texts]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if boxes[i].overlaps(boxes[j]):
                raise RuntimeError(f"direct labels overlap: {texts[i].get_text()!r} "
                                   f"and {texts[j].get_text()!r}")


# ---- Figures ---------------------------------------------------------------
def line_chart(summary, exp_ids, colors, column, ylabel, title, out, name):
    all_clients = sorted(summary.clients.unique())
    direct = len(exp_ids) > len(CATEGORICAL)
    width = 7.2
    fig, ax = plt.subplots(figsize=(width, 4.2))
    fig.subplots_adjust(left=0.1, right=0.72 if not direct else 0.86, top=0.9, bottom=0.14)
    ends = []
    for e in exp_ids:
        d = summary[summary.exp == e].sort_values("clients")
        c = colors[e]
        # Reindexed onto every client count of the workload: a count this
        # experiment did not run becomes NaN, which breaks the line there.
        line = d.set_index("clients")[column].reindex(all_clients)
        ax.plot(line.index, line.to_numpy(), color=c, lw=1.5, zorder=2)
        ok = d.valid
        ax.scatter(d.clients[ok], d[column][ok], s=30, color=c,
                   edgecolor=SURFACE, linewidth=1.2, zorder=3)
        # Invalid run: clients aborted or pgbench failed, so the point is not a
        # measurement at its labelled client count.
        ax.scatter(d.clients[~ok], d[column][~ok], s=34, facecolor=SURFACE,
                   edgecolor=c, linewidth=1.5, zorder=4)
        last = d.iloc[-1]
        ends.append((e, last.clients, last[column], c))

    ax.set_xscale("log", base=2)
    ax.set_xticks(all_clients, [str(c) for c in all_clients])
    ax.minorticks_off()
    ax.set_xlabel("clients")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left")

    handles = [Line2D([], [], color=colors[e], marker="o", ms=5, mec=SURFACE, label=e)
               for e in exp_ids]
    handles.append(Line2D([], [], ls="", marker="o", ms=5.5, mfc=SURFACE, mec=INK_2,
                          mew=1.3, label="hollow marker:\nnot valid"))
    parts = [invalid_note(summary, "Hollow markers are"),
             missing_clients_note(summary, exp_ids, all_clients)]
    if direct:
        label_line_ends(ax, ends)
        check_labels_disjoint(fig, [t for t in ax.texts])
        ncol = min(len(handles), 7)
        rows = -(-len(handles) // ncol)
        ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, -0.13), ncol=ncol,
                  fontsize=7.5, handlelength=1.5, columnspacing=1.2)
        # The legend sits under the x label; push the caption below its rows.
        caption(ax, parts, width, offset_pt=40 + 16 * rows)
    else:
        ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1.0))
        caption(ax, parts, width)
    save(fig, out, name)


def fold_transactions(tx):
    """(named transactions in id order, folded ones, share table) for one workload."""
    d = tx.copy()
    d["total_ms"] = d.avg_latency_ms * d.successful_transactions
    d["share"] = 100 * d.total_ms / d.groupby(["exp", "clients"]).total_ms.transform("sum")
    peak = d.groupby("transaction").share.max()
    named = peak[peak >= FOLD_BELOW_PCT].sort_values(ascending=False)
    named = sorted(named.index[:len(CATEGORICAL)], key=tx_key)
    folded = sorted((t for t in peak.index if t not in named), key=tx_key)
    return named, folded, d


def latency_share_chart(wl, clients, share, named, folded, summary, exp_ids, out):
    title_wl = f"Workload {wl.upper()}"
    d = share[share.clients == clients]
    p = d.pivot(index="exp", columns="transaction", values="share").reindex(
        index=exp_ids, columns=named + folded)
    segments = list(named)
    colors = [CATEGORICAL[i] for i in range(len(named))]
    if folded:
        p["Other"] = p[folded].sum(axis=1, min_count=1)
        segments.append("Other")
        colors.append(OTHER_COLOR)
    s_here = summary[summary.clients == clients]
    valid = s_here.set_index("exp").valid.reindex(exp_ids)

    n = len(exp_ids)
    width = 7.5
    fig, ax = plt.subplots(figsize=(width, 1.3 + 0.32 * n))
    y = np.arange(n)[::-1]                   # first experiment at the top
    left = np.zeros(n)
    for seg, col in zip(segments, colors):
        # Fallback: NaN means the experiment has no row for this segment (not run
        # at this client count, or the transaction is absent). A zero-width
        # segment draws nothing; whole missing rows are labelled "no data" below.
        vals = p[seg].fillna(0).to_numpy()
        ax.barh(y, vals, left=left, height=0.62, color=col, edgecolor=SURFACE,
                linewidth=0.8)
        for yi, l, v in zip(y, left, vals):
            if v >= SEGMENT_LABEL_MIN_PCT:
                ax.text(l + v / 2, yi, f"{v:.0f}", ha="center", va="center",
                        fontsize=7, color=ink_for(col), zorder=4, path_effects=halo(col))
        left += vals
    for yi, e in zip(y, exp_ids):
        if pd.isna(valid[e]):
            ax.text(1, yi, "no data", ha="left", va="center", fontsize=7, color=MUTED)
        elif not valid[e]:
            ax.add_patch(Rectangle((0, yi - 0.31), 100, 0.62, fill=False, hatch=HATCH,
                                   edgecolor=INK_2, linewidth=0, zorder=3))
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("share of total measured latency (%)")
    ax.set_yticks(y, exp_ids)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.set_title(f"{title_wl} share of total measured latency per transaction, "
                 f"{clients_label(clients)}", loc="left", pad=24)

    handles = [Patch(color=col, label=seg if seg != "Other" else f"Other ({', '.join(folded)})")
               for seg, col in zip(segments, colors)]
    if not valid.dropna().all():
        handles.append(Patch(facecolor=SURFACE, edgecolor=INK_2, hatch=HATCH,
                             linewidth=0.6, label="not valid"))
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(handles),
              handlelength=1.2, columnspacing=1.0, fontsize=7.5, borderaxespad=0.2)

    folded_note = ""
    if folded:
        folded_max = share[share.transaction.isin(folded)].groupby(
            ["exp", "clients"]).share.sum().max()
        folded_note = (f"{', '.join(folded)} never reach {FOLD_BELOW_PCT:g}% in any "
                       f"{title_wl} run and are folded into Other (max combined share "
                       f"{folded_max:.1f}%).")
    missing = [e for e in exp_ids if pd.isna(valid[e])]
    caption(ax, [
        "Share = avg_latency_ms x successful_transactions / sum over all transactions "
        "of that experiment at this client count. " + folded_note,
        invalid_note(s_here, "Hatched rows are"),
        f"No data at {clients_label(clients)}: {', '.join(missing)}." if missing else "",
    ], width)
    save(fig, out, f"latency_share_c{clients}")


def heatmap_chart(wl, clients, tx, column, norm, summary, exp_ids, transactions,
                  metric, out, name):
    g = tx[tx.clients == clients].pivot(index="exp", columns="transaction", values=column)
    g = g.reindex(index=exp_ids, columns=transactions).to_numpy(dtype=float)
    cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
    cmap.set_bad(BAND)
    s_here = summary[summary.clients == clients]
    valid = s_here.set_index("exp").valid.reindex(exp_ids)

    n, m = len(exp_ids), len(transactions)
    width = 1.6 + 0.62 * m
    fig, ax = plt.subplots(figsize=(width, 1.3 + 0.34 * n))
    im = ax.imshow(np.ma.masked_invalid(g), cmap=cmap, norm=norm, aspect="auto")
    for i in range(n):
        for j in range(m):
            if np.isnan(g[i, j]):
                ax.text(j, i, "n/a", ha="center", va="center", fontsize=6.5, color=MUTED)
                continue
            fill = to_hex(cmap(norm(g[i, j])))
            ax.text(j, i, fmt_ms(g[i, j]), ha="center", va="center", fontsize=6.8,
                    color=ink_for(fill), zorder=4, path_effects=halo(fill))
    for i, e in enumerate(exp_ids):
        if not pd.isna(valid[e]) and not valid[e]:
            ax.add_patch(Rectangle((-0.5, i - 0.5), m, 1, fill=False, hatch=HATCH,
                                   edgecolor=INK_2, linewidth=0, zorder=3))
    ax.set_xticks(range(m), transactions)
    ax.set_yticks(range(n), exp_ids)
    ax.tick_params(length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(f"Workload {wl.upper()} {metric} latency per transaction, "
                 f"{clients_label(clients)}", loc="left")
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cb.set_label(f"{metric} latency (ms, log scale)", color=INK_2)
    cb.outline.set_visible(False)
    cb.ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))

    missing = [e for e in exp_ids if pd.isna(valid[e])]
    has_data = ~valid.isna().to_numpy()
    caption(ax, [
        f"Colour scale shared by every Workload {wl.upper()} {metric} heatmap.",
        invalid_note(s_here, "Hatched rows are"),
        f"No data at {clients_label(clients)}: {', '.join(missing)}." if missing else "",
        "n/a: transaction not measured in that experiment."
        if np.isnan(g[has_data]).any() else "",
    ], width, offset_pt=22)
    save(fig, out, name)


def shared_log_norm(tx, column, path_hint):
    vals = tx[column]
    if (vals <= 0).any():
        bad = tx.loc[vals <= 0, ["exp", "clients", "transaction", column]]
        raise RuntimeError(f"{path_hint}: non-positive {column} cannot go on a log scale:\n{bad}")
    return LogNorm(vmin=vals.min(), vmax=vals.max())


def plot_workload(wl, summary, tx, out):
    out.mkdir(parents=True, exist_ok=True)
    # This script owns these names; remove last run's outputs so a client count
    # that no longer exists does not leave a stale file behind.
    for pattern in ("throughput.*", "latency_*.*", "heatmap_*.*"):
        for f in out.glob(pattern):
            f.unlink()

    exp_ids = list(summary.drop_duplicates("exp").sort_values("exp_index").exp)
    colors = experiment_colors(exp_ids)
    title_wl = f"Workload {wl.upper()}"
    all_clients = sorted(summary.clients.unique())
    transactions = sorted(tx.transaction.unique(), key=tx_key)

    line_chart(summary, exp_ids, colors, "overall_tps",
               "overall throughput (TPS, log scale)",
               f"{title_wl} throughput by client count", out, "throughput")
    for label, col in (("p50", "overall_median_latency_ms"), ("p95", "overall_p95_latency_ms"),
                       ("p99", "overall_p99_latency_ms")):
        line_chart(summary, exp_ids, colors, col, f"overall {label} latency (ms, log scale)",
                   f"{title_wl} {label} latency by client count", out, f"latency_{label}")

    named, folded, share = fold_transactions(tx)
    for c in all_clients:
        latency_share_chart(wl, c, share, named, folded, summary, exp_ids, out)

    for column, metric, prefix in (("avg_latency_ms", "average", "heatmap_avg"),
                                   ("p99_latency_ms", "p99", "heatmap_p99")):
        norm = shared_log_norm(tx, column, f"workload {wl}")
        for c in all_clients:
            heatmap_chart(wl, c, tx, column, norm, summary, exp_ids, transactions, metric,
                          out, f"{prefix}_c{c}")
    return sorted(p.name for p in out.iterdir() if p.suffix == ".png")


# ---- Validity table --------------------------------------------------------
def validity_table(summary, out):
    cols = ["workload", "exp", "clients", "overall_tps", "failed_log_records",
            "serialization_failures", "deadlock_failures", "pgbench_exit_code",
            "aborted_clients", "valid"]
    v = summary.sort_values(["workload", "exp_index", "clients"])[cols].reset_index(drop=True)
    v.to_csv(out / "validity.csv", index=False)
    return v


def run(repo, out):
    start = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    workloads = discover(repo)
    summaries = []
    written = {}
    for wl, exps in workloads.items():
        summary, tx = load_workload(exps)
        summaries.append(summary)
        written[wl] = plot_workload(wl, summary, tx, out / wl)

    v = validity_table(pd.concat(summaries, ignore_index=True), out)
    with pd.option_context("display.width", 200, "display.max_rows", 500):
        print(v.to_string(index=False))
    for wl, names in written.items():
        print(f"\nWorkload {wl.upper()}: {len(names)} PNG (+PDF) in {out / wl}")
        print("  " + " ".join(names))
    print(f"\nFigures written to {out} in {time.perf_counter() - start:.1f}s")
    return written


def main():
    run(REPO, REPO / "analysis" / "figures")


if __name__ == "__main__":
    main()
