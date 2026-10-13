"""Write pgfplots figures and tables for the Task 4 evidence pack.

Run after collect_pack.py:  python3 analysis/task4/pack_figures.py

Reads analysis/task4/pack/*.csv and writes, in that folder:
  figures.tex           figures and tables in the report's style (colours bcA ..
                        bcInert, macros \\expt, \\txn, \\code); the ablation grid
                        needs \\usepackage{colortbl}
  figures_preview.tex   standalone document that \\input's figures.tex
"""

import math
import sys
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True  # no __pycache__ next to the scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))
from narrative_figures import STYLE, coords, wrap  # noqa: E402

D = Path(__file__).resolve().parent / "pack"
CLIENTS = [1, 4, 8, 16, 32, 64]


def num(x, d=1):
    return f"{x:,.{d}f}".replace(",", "{,}")


# ------------------------------------------------- A vs B, step by step
def fig_steps():
    S = pd.read_csv(D / "a_vs_b_chain.csv").iloc[1:].reset_index(drop=True)
    short = ["colocate", "T3 join", "set-based T1", "T7 map", "T5 map", "T6 rollup", "T1 delegated",
             "8 shards", "4 shards"]
    labels = ",".join(f"{{{s}\\\\[-1pt]\\expt{{b{7 + i}}}/a{7 + i}}}" for i, s in enumerate(short))
    b = [(i, S.b_mean_tps_x_step[i]) for i in range(len(S))]
    a = [(i, S.a_mean_tps_x_step[i]) for i in range(len(S))]
    notes = []
    for i in (3, 5, 6):
        notes.append(f"  \\node[font=\\tiny,anchor=south,text=bcA] at (axis cs:{i - 0.17},{S.b_mean_tps_x_step[i] * 1.05:.3f}) "
                     f"{{{S.b_mean_tps_x_step[i]:.2f}}};")
        notes.append(f"  \\node[font=\\tiny,anchor=south,text=bcB] at (axis cs:{i + 0.17},{S.a_mean_tps_x_step[i] * 1.05:.3f}) "
                     f"{{{S.a_mean_tps_x_step[i]:.2f}}};")
    notes.append(f"  \\node[font=\\tiny,anchor=south,text=bcB,align=center] at (axis cs:1.17,{S.a_mean_tps_x_step[1] * 1.05:.2f}) "
                 "{{not valid}};")
    body = rf"""  \begin{{tikzpicture}}
  \begin{{axis}}[narr,
    width=\linewidth, height=5cm,
    ybar, bar width=7pt,
    ymode=log, log origin=infty, ymin=0.7, ymax=120,
    ytick={{1,2,5,10,20,50,100}}, yticklabels={{1,2,5,10,20,50,100}},
    xmin=-0.6, xmax={len(S) - 0.4}, xtick={{0,...,{len(S) - 1}}}, xticklabels={{{labels}}},
    x tick label style={{align=center,font=\tiny}},
    ylabel={{Mean TPS $\div$ previous step}},
    ymajorgrids, xtick pos=bottom, ytick pos=left,
    legend style={{at={{(0.99,0.97)}},anchor=north east,legend columns=-1}},
  ]
  \draw[black!55,line width=0.6pt] (axis cs:-0.6,1) -- (axis cs:{len(S) - 0.4},1);
  \addplot[fill=bcA,draw=none] coordinates {{{coords(b, '{:.3f}')}}};
  \addlegendentry{{workload B}}
  \addplot[fill=bcB,draw=none] coordinates {{{coords(a, '{:.3f}')}}};
  \addlegendentry{{workload A}}
{chr(10).join(notes)}
  \end{{axis}}
  \end{{tikzpicture}}"""
    return wrap("fig:b-vs-a-steps",
                r"The same nine steps on both workloads: mean TPS of each step divided by the step before. "
                r"T7 routing and the rollup pay more on B, where \txn{7} is 30\% and \txn{6} 10\% of the "
                r"mix (5\% each on A); delegating \txn{1} pays more on A, where \txn{1} is 36\% of the mix "
                r"(10\% on B). The A runs used a different node set, so only the ratios are compared; "
                r"\expt{a8} is not valid from 4 clients up (most clients aborted).", body)


# ------------------------------------------------------ final benchmark
def tab_final():
    F = pd.read_csv(D / "final_benchmark.csv", index_col=0)
    rows = []
    for k in [str(c) for c in CLIENTS] + ["mean"]:
        r = F.loc[k]
        lab = "Mean" if k == "mean" else k
        p99 = "" if k == "mean" else f"{r.overall_p99_latency_ms_mean:.1f} $\\pm$ {r.overall_p99_latency_ms_se:.2f}"
        rt = "" if k == "mean" else f"{num(r.retried_transactions_mean, 0)}"
        rows.append(f"    {lab} & {num(r.b19)} & {num(r.b20)} & {num(r.b21)} & \\textbf{{{num(r['mean'])}}} & "
                    f"{r.se:.1f} & {num(r.ci95_lo)}--{num(r.ci95_hi)} & {r.cv_pct:.2f} & {p99} & {rt} \\\\")
    body = r"""  \small\setlength{\tabcolsep}{3.5pt}
  \begin{tabular}{@{}lrrrrrrrrr@{}}
    \toprule
    & \multicolumn{3}{c}{TPS} & & & & & \multicolumn{2}{c}{Mean of 3} \\
    \cmidrule(lr){2-4}\cmidrule(l){9-10}
    Clients & \expt{b19} & \expt{b20} & \expt{b21} & Mean & SE & 95\% CI & CV (\%) & p99 (ms) & Retried \\
    \midrule
""" + "\n".join(rows) + r"""
    \bottomrule
  \end{tabular}"""
    return wrap("tab:b-final",
                r"The final design, run three times (\expt{b19} on 2026-09-28, \expt{b20} and \expt{b21} on "
                r"2026-10-11). SE is the standard error of the mean of the three runs; the 95\% interval "
                r"uses Student's $t$ with 2 degrees of freedom. p99 is the 99th-percentile latency and "
                r"Retried the number of transactions pgbench retried at least once, both as mean $\pm$ SE "
                r"or mean of the three runs.", body).replace("\\begin{figure}", "\\begin{table}").replace(
        "\\end{figure}", "\\end{table}")


# ---------------------------------------------------------- partitions
def fig_partitions():
    V = pd.read_csv(D / "vs_final.csv", index_col=0)
    F = pd.read_csv(D / "final_benchmark.csv", index_col=0)
    series = [("expt_b30", "bcGrey", "o", r"\expt{b30}: \expt{b19}, \txn{1} not delegated"),
              ("expt_b22", "bcB", "triangle*", r"\expt{b22}: catalog by \code{product\_id}"),
              ("expt_b23", "bcC", "square*", r"\expt{b23}: orders by \code{order\_id}"),
              ("expt_b24", "bcD", "diamond*", r"\expt{b24}: catalog on one node"),
              ("expt_b25", "bcE", "pentagon*", r"\expt{b25}: inventory a reference table")]
    fin = " ".join(f"({c},{F.loc[str(c), 'mean']:.1f}) +- (0,{4.303 * F.loc[str(c), 'se']:.1f})" for c in CLIENTS)
    plots = [f"  \\addplot[bcA,line width=1.6pt,mark=*,mark size=1.8pt,error bars/.cd,y dir=both,y explicit] "
             f"coordinates {{{fin}}};\n  \\addlegendentry{{final design (\\expt{{b19}}--\\expt{{b21}})}}"]
    for e, col, mark, name in series:
        pts = [(c, V.loc[e, f"c{c}"]) for c in CLIENTS]
        plots.append(f"  \\addplot[{col},line width=1.1pt,mark={mark},mark size=1.8pt] "
                     f"coordinates {{{coords(pts, '{:.1f}')}}};\n  \\addlegendentry{{{name}}}")
    body = rf"""  \begin{{tikzpicture}}
  \begin{{axis}}[narr,
    width=0.85\linewidth, height=5.6cm,
    xmode=log, log basis x=2, xmin=0.8, xmax=80,
    xtick={{1,4,8,16,32,64}}, xticklabels={{1,4,8,16,32,64}},
    ymode=log, ymin=100, ymax=6000,
    ytick={{100,200,500,1000,2000,5000}}, yticklabels={{100,200,500,1{{,}}000,2{{,}}000,5{{,}}000}},
    xlabel={{Clients}}, ylabel={{TPS}}, grid=major,
    legend style={{at={{(0.5,1.03)}},anchor=south,legend columns=2,font=\tiny}},
  ]
{chr(10).join(plots)}
  \end{{axis}}
  \end{{tikzpicture}}"""
    return wrap("fig:b-partitions",
                r"The four alternative placements against the final design (error bars: 95\% interval of "
                r"the three runs, smaller than the markers). \expt{b22}, \expt{b24} and \expt{b25} move "
                r"\tbl{inventory} off the merchant's worker, so their \txn{1} cannot be delegated; "
                r"\expt{b30}, the ablation cell with only \txn{1} delegation off, isolates that change. "
                r"\expt{b22} and \expt{b24} beat \expt{b30} but not the final design; \expt{b25} "
                r"serialises every \tbl{inventory} write.", body)


# ------------------------------------------------------------ ablation
def tab_ablation():
    C = pd.read_csv(D / "ablation_cells.csv")
    cols = [(1, 1), (0, 1), (1, 0), (0, 0)]          # (T6 rollup, T7 routing)
    rows = [(1, 1), (1, 0), (0, 1), (0, 0)]          # (T5 routing, T1 delegated)
    lo, hi = math.log(0.07), math.log(1.0)

    def shade(r):
        k = max(0.0, min(1.0, (math.log(r) - lo) / (hi - lo)))
        return round(8 + 72 * k)

    def onoff(v):
        return "on" if v else "off"

    def grid(metric, title):
        lines = [r"    \begin{tabular}{@{}ll|cccc@{}}",
                 rf"      \multicolumn{{2}}{{c|}}{{{title}}} & \multicolumn{{4}}{{c}}{{T6 rollup / T7 routing}} \\",
                 r"      T5 & T1 & " + " & ".join(f"{onoff(a)}/{onoff(b)}" for a, b in cols) + r" \\",
                 r"      \hline"]
        for t5, t1 in rows:
            cells = []
            for t6, t7 in cols:
                r = C[(C.T5_on == t5) & (C.T1_on == t1) & (C.T6_on == t6) & (C.T7_on == t7)].iloc[0]
                v = r[metric]
                s = shade(v)
                txt = f"{100 * v:.0f}" + ("$^\\dagger$" if not r.valid else "")
                if s > 50:
                    txt = f"\\textcolor{{white}}{{{txt}}}"
                cells.append(f"\\cellcolor{{bcA!{s}}}{txt}")
            lines.append(f"      {onoff(t5)} & {onoff(t1)} & " + " & ".join(cells) + r" \\")
        lines.append(r"    \end{tabular}")
        return "\n".join(lines)

    body = ("  \\small\\setlength{\\tabcolsep}{5pt}\\renewcommand{\\arraystretch}{1.25}\n"
            + grid("ratio_mean", "mean TPS") + "\\hspace{1.2em}\n" + grid("ratio_c64", "TPS at 64 clients"))
    return wrap("tab:b-ablation-grid",
                r"The $2^4$ ablation around the final design: TPS as a percentage of the final design's "
                r"(mean of \expt{b19}--\expt{b21}), averaged over the six client counts (left) and at 64 "
                r"clients (right). Rows switch T5 routing and \txn{1} delegation, columns the T6 rollup "
                r"and T7 routing; the top-left cell is the final design. Darker is faster (logarithmic "
                r"shading). $^\dagger$ marks cells with aborted clients: \txn{1}'s commit failed on a "
                r"\code{SERIALIZABLE} conflict, which pgbench does not retry.",
                body).replace("\\begin{figure}", "\\begin{table}").replace("\\end{figure}", "\\end{table}")


# --------------------------------------------------------------- shards
def fig_shards():
    S = pd.read_csv(D / "shards.csv")
    style = {1: ("bcE", "pentagon*"), 2: ("bcD", "diamond*"), 4: ("bcA", "*"), 8: ("bcC", "square*"),
             16: ("bcB", "triangle*"), 32: ("bcGrey", "o")}
    plots = []
    for _, r in S.iterrows():
        n = int(r.shards)
        col, mark = style[n]
        if n == 4:
            pts = " ".join(f"({c},{r[f'tps_c{c}']:.1f}) +- (0,{4.303 * r[f'se_c{c}']:.1f})" for c in CLIENTS)
            plots.append(f"  \\addplot[{col},line width=1.6pt,mark={mark},mark size=1.8pt,error bars/.cd,"
                         f"y dir=both,y explicit] coordinates {{{pts}}};\n  \\addlegendentry{{4 (final)}}")
        else:
            pts = [(c, r[f"tps_c{c}"]) for c in CLIENTS]
            plots.append(f"  \\addplot[{col},line width=1.1pt,mark={mark},mark size=1.8pt] "
                         f"coordinates {{{coords(pts, '{:.1f}')}}};\n  \\addlegendentry{{{n}}}")
    t6 = [(int(r.shards), r.t6_c64_ms) for _, r in S.iterrows()]
    body = rf"""  \begin{{minipage}}[t]{{0.6\linewidth}}
  \centering
  \begin{{tikzpicture}}[baseline=(current axis.south)]
  \begin{{axis}}[narr,
    width=\linewidth, height=5.4cm, title={{TPS by shard count}},
    xmode=log, log basis x=2, xmin=0.8, xmax=80,
    xtick={{1,4,8,16,32,64}}, xticklabels={{1,4,8,16,32,64}},
    ymin=0, ymax=4500, ytick={{0,1000,2000,3000,4000}}, scaled y ticks=false,
    yticklabel style={{/pgf/number format/1000 sep={{{{,}}}}}},
    xlabel={{Clients}}, ylabel={{TPS}}, grid=major,
    legend style={{at={{(0.02,0.98)}},anchor=north west,legend columns=2,font=\tiny}},
  ]
{chr(10).join(plots)}
  \end{{axis}}
  \end{{tikzpicture}}
  \end{{minipage}}\hfill
  \begin{{minipage}}[t]{{0.38\linewidth}}
  \centering
  \begin{{tikzpicture}}[baseline=(current axis.south)]
  \begin{{axis}}[narr,
    width=\linewidth, height=5.4cm, title={{\txn{{6}} at 64 clients}},
    xmode=log, log basis x=2, xmin=0.7, xmax=45,
    xtick={{1,2,4,8,16,32}}, xticklabels={{1,2,4,8,16,32}},
    ymin=0, ymax=300, ytick={{0,100,200,300}},
    xlabel={{Shards per table}}, ylabel={{Mean latency (ms)}}, ymajorgrids,
  ]
  \addplot[bcA,line width=1.1pt,mark=*,mark size=1.8pt] coordinates {{{coords(t6, '{:.1f}')}}};
  \end{{axis}}
  \end{{tikzpicture}}
  \end{{minipage}}"""
    return wrap("fig:b-shards",
                r"The final design with 1 to 32 shards per table (4 is the final design; error bars: 95\% "
                r"interval of its three runs). Left: fewer shards win at low load, because fewer "
                r"transactions commit across workers, but put all the data on one or two workers. Right: "
                r"\txn{6} runs one task per shard and is cheapest with one shard per worker.", body)


PREVIEW = r"""\documentclass[11pt]{article}
\usepackage[a4paper,margin=2.5cm]{geometry}
\usepackage{xcolor,colortbl,booktabs,pgfplots}
\pgfplotsset{compat=1.18}
\usepackage{hyperref,cleveref}
\newcommand{\expt}[1]{\textsf{#1}}
\newcommand{\txn}[1]{T#1}
\newcommand{\tbl}[1]{\texttt{#1}}
\newcommand{\code}[1]{\texttt{#1}}
\definecolor{bcA}{HTML}{2B58C0}
\definecolor{bcB}{HTML}{C94A00}
\definecolor{bcC}{HTML}{00A6A0}
\definecolor{bcD}{HTML}{C79100}
\definecolor{bcE}{HTML}{8E44AD}
\definecolor{bcGrey}{HTML}{6B7280}
\definecolor{bcInert}{HTML}{BFC4CB}
\begin{document}
\input{figures.tex}
\end{document}
"""


def main():
    parts = [fig_steps(), tab_final(), fig_partitions(), tab_ablation(), fig_shards()]
    (D / "figures.tex").write_text(
        "% Generated by analysis/task4/pack_figures.py from analysis/task4/pack/*.csv.\n"
        "% Needs \\usepackage{colortbl} for the ablation grid. Do not edit numbers by hand.\n\n"
        + STYLE + "\n" + "\n".join(parts), encoding="utf-8")
    (D / "figures_preview.tex").write_text(PREVIEW, encoding="utf-8")
    print(f"wrote {len(parts)} figures/tables to {D / 'figures.tex'}")


if __name__ == "__main__":
    main()
