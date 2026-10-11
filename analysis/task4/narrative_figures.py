"""Write pgfplots code for the workload-B narrative figures.

Run after collect_narrative.py:  python3 analysis/task4/narrative_figures.py

Reads analysis/task4/narrative/*.csv and writes, in the same folder:
  figures.tex           one figure environment per proposed figure, numbers
                        taken from the CSVs (paste into the report; it uses the
                        colours bcA..bcInert and the macros \\expt, \\txn already
                        defined for Section 5)
  figures_preview.tex   a standalone document that \\input's figures.tex, to
                        compile and look at:  latexmk -pdf figures_preview.tex
"""

from pathlib import Path

import pandas as pd

D = Path(__file__).resolve().parent / "narrative"
CLIENTS = [1, 4, 8, 16, 32, 64]


def coords(pairs, fmt="{:.4g}"):
    return " ".join(f"({x},{fmt.format(y)})" for x, y in pairs)


def wrap(label, caption, body):
    return (f"\\begin{{figure}}[htbp]\n  \\centering\n{body}\n"
            f"  \\caption{{{caption}}}\n  \\label{{{label}}}\n\\end{{figure}}\n")


STYLE = r"""% Shared axis style for the narrative figures (matches the Section 5 figures).
\pgfplotsset{narr/.style={
  grid style={line width=0.3pt,draw=black!14},
  tick label style={font=\scriptsize}, label style={font=\scriptsize},
  title style={font=\scriptsize,yshift=-3pt},
  legend cell align=left,
  legend style={draw=none,fill=none,font=\scriptsize,
    nodes={text height=1.5ex,text depth=0.25ex},
    /tikz/every even column/.append style={column sep=6pt}},
}}
"""


# ----------------------------------------------------------- figure A
def fig_latency_by_tx():
    L = pd.read_csv(D / "latency_by_tx.csv", index_col=0)
    plots = []
    for e, col in (("b0", "bcGrey"), ("b7", "bcD"), ("b8", "bcA")):
        pts = [(i + 1, L.loc[f"T{i + 1}", f"{e}_c1"]) for i in range(9)]
        plots.append(f"  \\addplot[fill={col},draw=none] coordinates {{{coords(pts)}}};\n"
                     f"  \\addlegendentry{{\\expt{{{e}}}}}")
    labels = ",".join(f"{{\\txn{{{i}}}\\\\{round(100 * L.loc[f'T{i}', 'weight'])}\\%}}" for i in range(1, 10))
    t3, t4, t7 = (L.loc[t] for t in ("T3", "T4", "T7"))
    notes = (
        f"  \\node[font=\\tiny,align=center] at (axis cs:3,7000) {{{t3.b0_c1:,.0f}$\\to${t3.b8_c1:.1f}}};\n"
        f"  \\node[font=\\tiny,align=center] at (axis cs:4,7000) {{{t4.b0_c1:.0f}$\\to${t4.b7_c1:.1f}}};\n"
        f"  \\node[font=\\tiny,align=center] at (axis cs:7,7000) {{{t7.b0_c1:.0f}, {t7.b7_c1:.0f}, {t7.b8_c1:.0f}}};"
    )
    body = rf"""  \begin{{tikzpicture}}
  \begin{{axis}}[narr,
    width=\linewidth, height=4.6cm,
    ybar, bar width=5pt,
    ymode=log, log origin=infty, ymin=0.5, ymax=20000,
    ytick={{1,10,100,1000}}, yticklabels={{1,10,100,1{{,}}000}},
    xmin=0.4, xmax=9.6, xtick={{1,...,9}}, xticklabels={{{labels}}},
    x tick label style={{align=center}},
    ylabel={{Mean latency, 1 client (ms)}},
    ymajorgrids, xtick pos=bottom, ytick pos=left,
    legend style={{at={{(0.5,1.03)}},anchor=south,legend columns=-1}},
  ]
{chr(10).join(plots)}
{notes}
  \end{{axis}}
  \end{{tikzpicture}}"""
    return wrap("fig:b-a-design-latency",
                r"Mean latency of each transaction at one client, before (\expt{b0}) and after applying "
                r"workload A's design (\expt{b7}, \expt{b8}); the second label line is the transaction's "
                r"weight in workload B. \txn{3} and \txn{4} fall by three orders of magnitude once they "
                r"reach a single shard, while \txn{7}, 30\% of the mix, stays at about 30\,ms.", body)


# ----------------------------------------------------------- figure B
def fig_clients_inside():
    C = pd.read_csv(D / "clients_inside_c64.csv", index_col=0)
    order = ["b0", "b7", "b8", "b9", "b10", "b11", "b12", "b13", "b14", "b15", "b19"]
    C = C.loc[order]
    C["other"] = C[["T2", "T4", "T8", "T9"]].sum(axis=1)
    layers = [("T7", "bcA", r"\txn{7}"), ("T1", "bcE", r"\txn{1}"), ("T6", "bcD", r"\txn{6}"),
              ("T5", "bcC", r"\txn{5}"), ("T3", "bcB", r"\txn{3}"),
              ("other", "bcInert", r"\txn{2}, \txn{4}, \txn{8}, \txn{9}")]
    plots = []
    for col, colour, name in layers:
        pts = [(i, C.iloc[i][col]) for i in range(len(C))]
        plots.append(f"  \\addplot[fill={colour},draw=white,line width=0.4pt] coordinates {{{coords(pts, '{:.2f}')}}};\n"
                     f"  \\addlegendentry{{{name}}}")
    body = rf"""  \begin{{tikzpicture}}
  \begin{{axis}}[narr,
    width=\linewidth, height=4.8cm,
    ybar stacked, bar width=11pt,
    ymin=0, ymax=70, ytick={{0,16,32,48,64}},
    xmin=-0.6, xmax={len(C) - 0.4}, xtick={{0,...,{len(C) - 1}}},
    xticklabels={{{",".join(order)}}},
    ylabel={{Clients inside, 64 clients}},
    ymajorgrids, xtick pos=bottom, ytick pos=left,
    area legend,
    legend style={{at={{(0.5,1.03)}},anchor=south,legend columns=-1}},
  ]
{chr(10).join(plots)}
  \end{{axis}}
  \end{{tikzpicture}}"""
    other_b0 = C.loc["b0", "T4"]
    return wrap("fig:b-clients-inside",
                r"Where the 64 clients are at any moment, by Little's law (throughput $\times$ mean "
                r"latency of each transaction), along the main chain. Each fix moves the queue to the "
                r"next transaction: \txn{3} (\expt{b0}, \expt{b7}), \txn{7} (\expt{b8}, \expt{b9}), "
                r"\txn{5} (\expt{b10}), \txn{6} (\expt{b11}--\expt{b14}) and \txn{7} again, now "
                r"without a majority (\expt{b15} on). Grey is mostly \txn{4} in \expt{b0} "
                f"({other_b0:.1f} clients). Bars below 64 (\\expt{{b0}}) or above it (\\expt{{b7}}) come "
                r"from transactions of several seconds that straddle the end of the 600\,s run.", body)


# ----------------------------------------------------------- figure C
def fig_serialised():
    T = pd.read_csv(D / "tx_by_clients.csv").set_index(["transaction", "clients"])

    def series(tx, e):
        return [(c, T.loc[(tx, c), f"{e}_lat"]) for c in CLIENTS]

    def panel(title, lines, ylabel):
        out = []
        for tx, e, colour, mark, label in lines:
            out.append(f"  \\addplot[{colour},line width=1.1pt,mark={mark},mark size=1.7pt] "
                       f"coordinates {{{coords(series(tx, e), '{:.3g}')}}};\n  \\addlegendentry{{{label}}}")
        return rf"""  \begin{{minipage}}[t]{{0.33\linewidth}}
  \centering
  \begin{{tikzpicture}}[baseline=(current axis.south)]
  \begin{{axis}}[narr,
    width=\linewidth, height=4.6cm, title={{{title}}},
    xmode=log, log basis x=2, xmin=0.8, xmax=80,
    xtick={{1,4,16,64}}, xticklabels={{1,4,16,64}},
    ymode=log, ymin=0.8, ymax=30000,
    ytick={{1,10,100,1000,10000}}, yticklabels={{1,10,100,1k,10k}},
    xlabel={{Clients}}, ylabel={{{ylabel}}}, grid=major,
    legend style={{at={{(0.5,-0.3)}},anchor=north,legend columns=2,font=\tiny}},
  ]
{chr(10).join(out)}
  \end{{axis}}
  \end{{tikzpicture}}
  \end{{minipage}}"""

    a = panel(r"\tbl{orders}: \txn{1} and \txn{5}",
              [("T1", "b7", "bcB", "*", r"\txn{1}, \expt{b7}"),
               ("T5", "b7", "bcB", "triangle*", r"\txn{5}, \expt{b7}"),
               ("T1", "b8", "bcA", "*", r"\txn{1}, \expt{b8}"),
               ("T5", "b8", "bcA", "triangle*", r"\txn{5}, \expt{b8}")], "Mean latency (ms)")
    b = panel(r"\tbl{inventory}: \txn{7}",
              [("T7", "b8", "bcB", "square*", r"\expt{b8}"),
               ("T7", "b10", "bcA", "square*", r"\expt{b10}")], "")
    c = panel(r"\tbl{orders}: \txn{5}",
              [("T5", "b9", "bcGrey", "triangle*", r"\expt{b9}"),
               ("T5", "b10", "bcB", "triangle*", r"\expt{b10}"),
               ("T5", "b11", "bcA", "triangle*", r"\expt{b11}")], "")
    def flat(tx, e, lo):
        """Min and max of a transaction's own TPS from `lo` clients on."""
        v = [T.loc[(tx, c), f"{e}_tps"] for c in CLIENTS if c >= lo]
        return min(v), max(v)

    t7lo, t7hi = flat("T7", "b8", 4)
    t5lo, t5hi = flat("T5", "b10", 8)
    cap = (r"Three times in the chain, a transaction whose \code{UPDATE} lacks \code{merchant\_id} "
           r"goes to every shard and Citus lets only one such multi-shard modification hold a shard "
           r"at a time, so these transactions queue behind each other (orange); routing them to one "
           r"shard removes the queue (blue). Left: in \expt{b7}, \txn{1}'s final \code{UPDATE orders} "
           r"and \txn{5} share one queue and have the same latency at every client count "
           f"({T.loc[('T1', 64), 'b7_lat']:,.0f} and {T.loc[('T5', 64), 'b7_lat']:,.0f}\\,ms at 64). "
           r"Middle: \txn{7}'s updates by \code{inventory\_id} in \expt{b8} complete "
           f"{t7lo:.1f}--{t7hi:.1f} times per second from 4 clients on, "
           r"whatever the load. Right: once \txn{7} is routed (\expt{b10}), \txn{5}, unchanged since "
           f"\\expt{{b8}}, hits the same kind of limit at {t5lo:.1f}--{t5hi:.1f} per second from 8 clients on.")
    return wrap("fig:b-serialised", cap, f"{a}%\n{b}%\n{c}")


# ----------------------------------------------------------- figure D
VARIANTS = [("b16", "bcB", "triangle*", "delegated"), ("b17", "bcC", "*", "reference table"),
            ("b18", "bcD", "diamond*", "merged lookup"), ("b19", "bcA", "square*", "both")]


def fig_t7_variants():
    T = pd.read_csv(D / "t7_latency.csv").set_index(["experiment", "clients"]).avg_latency_ms
    R = pd.read_csv(D / "rel_tps.csv")
    R = R[R.reference == "b15"].set_index(["experiment", "clients"])
    shift = {"b16": 0.93, "b17": 0.977, "b18": 1.023, "b19": 1.07}
    left, right = [], []
    for e, colour, mark, name in VARIANTS:
        pts = [(c, T[f"expt_{e}", c] / T["expt_b15", c]) for c in CLIENTS]
        left.append(f"  \\addplot[{colour},line width=1.1pt,mark={mark},mark size=1.7pt] "
                    f"coordinates {{{coords(pts, '{:.3f}')}}};\n  \\addlegendentry{{\\expt{{{e}}} {name}}}")
        err = " ".join(f"({c * shift[e]:.3f},{R.loc[(e, c), 'ratio']:.3f}) +- "
                       f"(0,{(R.loc[(e, c), 'ci95_hi'] - R.loc[(e, c), 'ci95_lo']) / 2:.3f})" for c in CLIENTS)
        right.append(f"  \\addplot[{colour},line width=1.1pt,mark={mark},mark size=1.7pt,"
                     f"error bars/.cd,y dir=both,y explicit,error bar style={{line width=0.6pt}}] "
                     f"coordinates {{{err}}};")
    common = r"""xmode=log, log basis x=2, xmin=0.75, xmax=85,
    xtick={1,4,8,16,32,64}, xticklabels={1,4,8,16,32,64},
    xlabel={Clients}, grid=major,"""
    body = rf"""  \begin{{minipage}}[t]{{0.49\linewidth}}
  \centering
  \begin{{tikzpicture}}
  \begin{{axis}}[narr,
    width=\linewidth, height=5cm, title={{\txn{{7}} mean latency $\div$ \expt{{b15}}}},
    {common}
    ymin=0.5, ymax=2.3, ytick={{0.5,0.75,1,1.25,1.5,1.75,2,2.25}},
    yticklabel style={{/pgf/number format/fixed,/pgf/number format/precision=2}},
    ylabel={{Relative latency}},
    legend style={{at={{(0.5,1.12)}},anchor=south,legend columns=2}},
  ]
  \draw[black!55,line width=0.6pt] (axis cs:0.75,1) -- (axis cs:85,1);
{chr(10).join(left)}
  \end{{axis}}
  \end{{tikzpicture}}
  \end{{minipage}}\hfill
  \begin{{minipage}}[t]{{0.49\linewidth}}
  \centering
  \begin{{tikzpicture}}
  \begin{{axis}}[narr,
    width=\linewidth, height=5cm, title={{TPS $\div$ \expt{{b15}}}},
    {common}
    ymin=0.6, ymax=1.3, ytick={{0.6,0.7,0.8,0.9,1,1.1,1.2,1.3}},
    yticklabel style={{/pgf/number format/fixed,/pgf/number format/precision=1,/pgf/number format/fixed zerofill}},
    ylabel={{Relative TPS}},
  ]
  \fill[black!7] (axis cs:0.75,0.95) rectangle (axis cs:85,1.05);
  \draw[black!55,line width=0.6pt] (axis cs:0.75,1) -- (axis cs:85,1);
{chr(10).join(right)}
  \end{{axis}}
  \end{{tikzpicture}}
  \end{{minipage}}"""
    return wrap("fig:b-t7-variants",
                r"The four ways of routing \txn{7} that branch from \expt{b15}, at every client count. "
                r"Left: \txn{7}'s own mean latency. Right: total throughput; error bars are 95\% "
                r"intervals from ten 60\,s windows of the same run (within-run noise only), and the "
                r"shaded band is the $\pm$5\% run-to-run variation of the conditions check. Cutting "
                r"\txn{7}'s latency by a fifth (\expt{b19}) raises TPS by 6--10\% at 1--8 clients but "
                r"only 3\% at 64.", body)


# ----------------------------------------------------------- figure E
def fig_b16_hist():
    H = pd.read_csv(D / "t7_hist_c1.csv")
    P = pd.read_csv(D / "placement.csv").set_index("shards")
    same = 1 - P.loc[4, "p_t7_cross_worker"]
    H = H[H.bin_lo_ms <= 13]
    b15 = list(zip(H.bin_lo_ms, 100 * H.b15)) + [(13.25, 0)]
    b16 = list(zip(H.bin_lo_ms, 100 * H.b16)) + [(13.25, 0)]
    fast = 100 * H.loc[H.bin_lo_ms < 6, "b16"].sum()
    body = rf"""  \begin{{tikzpicture}}
  \begin{{axis}}[narr,
    width=0.8\linewidth, height=4.4cm,
    xmin=0, xmax=13.25, xtick={{0,2,...,12}},
    ymin=0, ymax=34, ytick={{0,5,...,30}},
    xlabel={{\txn{{7}} latency at 1 client (ms)}}, ylabel={{Share of calls per 0.25\,ms (\%)}},
    ymajorgrids, xtick pos=bottom, ytick pos=left,
    legend style={{at={{(0.99,0.97)}},anchor=north east}},
  ]
  \addplot[const plot,fill=bcInert,draw=none,area legend] coordinates {{{coords(b15, '{:.3f}')}}} \closedcycle;
  \addlegendentry{{\expt{{b15}}: lookups + routed updates}}
  \addplot[const plot,bcB,line width=1.1pt] coordinates {{{coords(b16, '{:.3f}')}}};
  \addlegendentry{{\expt{{b16}}: delegated \code{{transfer\_inventory}}}}
  \node[font=\tiny,align=center,text=bcB] at (axis cs:2.7,11.5) {{{fast:.1f}\%\\credit local}};
  \node[font=\tiny,align=center,text=bcB] at (axis cs:9.7,17.5) {{{100 - fast:.1f}\%\\credit remote:\\new connection}};
  \end{{axis}}
  \end{{tikzpicture}}"""
    return wrap("fig:b-b16-hist",
                r"Distribution of \txn{7}'s latency at one client. Delegated to the source merchant's "
                f"worker (\\expt{{b16}}), \\txn{{7}} is bimodal: {fast:.1f}\\% of calls take about 2.5\\,ms, "
                r"the rest about 9.5\,ms, with no call in between. The fast share matches the probability "
                r"that both products' merchants sit on the same worker, "
                f"{100 * same:.2f}\\%, computed from Citus's hash of \\code{{merchant\\_id}}; a remote "
                r"credit costs about 7\,ms because the worker backend opens a new connection on every call.",
                body)


# ----------------------------------------------------------- figure F
def fig_absorption():
    R = pd.read_csv(D / "response_time_delta.csv").set_index(["comparison", "clients"])
    S = pd.read_csv(D / "step_prediction.csv").set_index(["comparison", "clients"])
    comps = ["b17 vs b15", "b18 vs b15", "b19 vs b15"]
    bars = [("T7", "bcA", r"\txn{7}"), ("T1", "bcE", r"\txn{1}"), ("T6", "bcD", r"\txn{6}"),
            ("other", "bcInert", "others"), ("total", "black!70", "net")]

    def pct(v):
        return f"{100 * (v - 1):+.1f}\\%".replace("-", "$-$")

    def panel(c, ymin, ymax, ystep, legend, ylabel):
        out = []
        for col, colour, name in bars:
            pts = []
            for i, comp in enumerate(comps):
                r = R.loc[(comp, c)]
                v = r.total - r.T7 - r.T1 - r.T6 if col == "other" else r[col]
                pts.append((i, v))
            out.append(f"  \\addplot[fill={colour},draw=none] coordinates {{{coords(pts, '{:.3f}')}}};"
                       + (f"\n  \\addlegendentry{{{name}}}" if legend else ""))
        notes = []
        for i, comp in enumerate(comps):
            s = S.loc[(comp, c)]
            notes.append(f"  \\node[font=\\tiny,align=center,anchor=north] at (axis cs:{i},{ymax - 0.03 * (ymax - ymin):.3f}) "
                         f"{{{pct(s.pred_t7_only)}\\\\{pct(s.measured)}}};")
        return rf"""  \begin{{minipage}}[t]{{0.49\linewidth}}
  \centering
  \begin{{tikzpicture}}[baseline=(current axis.south)]
  \begin{{axis}}[narr,
    width=\linewidth, height=5cm, title={{{c} client{'s' if c > 1 else ''}}},
    ybar, bar width=5pt,
    ymin={ymin}, ymax={ymax}, ytick={{{ymin},{ymin + ystep},...,{ymax}}},
    yticklabel style={{/pgf/number format/fixed,/pgf/number format/precision=2}},
    xmin=-0.5, xmax=2.5, xtick={{0,1,2}},
    xticklabels={{\expt{{b17}},\expt{{b18}},\expt{{b19}}}},
    ylabel={{{ylabel}}},
    ymajorgrids, xtick pos=bottom, ytick pos=left,
    legend style={{at={{(0.5,-0.2)}},anchor=north,legend columns=-1}},
  ]
  \draw[black!55,line width=0.6pt] (axis cs:-0.5,0) -- (axis cs:2.5,0);
{chr(10).join(out)}
{chr(10).join(notes)}
  \end{{axis}}
  \end{{tikzpicture}}
  \end{{minipage}}"""

    a = panel(1, -0.8, 0.4, 0.2, legend=False, ylabel="Change in mean response time (ms)")
    b = panel(64, -2.0, 1.5, 0.5, legend=True, ylabel="")
    s19 = S.loc[("b19 vs b15", 64)]
    r19 = R.loc[("b19 vs b15", 64)]
    return wrap("fig:b-absorption",
                r"Where \txn{7}'s saving went. Each bar is a transaction's weight times the change in its "
                r"mean latency against \expt{b15}; they sum to the change in mean response time per "
                r"transaction (net), and with no think time TPS $=$ clients $/$ response time, which "
                r"predicts every measured ratio here within 0.2\%. The labels give the TPS change that "
                r"\txn{7}'s latency alone would predict (top) and the measured change (bottom). At 64 "
                f"clients \\txn{{1}} and \\txn{{6}} slow down by {r19.T1 + r19.T6:.2f}\\,ms of the "
                f"{-r19.T7:.2f}\\,ms that \\txn{{7}} saves in \\expt{{b19}}, so the predicted "
                f"{100 * (s19.pred_t7_only - 1):+.0f}\\% becomes {100 * (s19.measured - 1):+.0f}\\%. "
                r"\expt{b16} is left out: its \txn{7} adds 5.2\,ms at 64 clients.",
                f"{a}\\hfill\n{b}")


PREVIEW = r"""\documentclass[11pt]{article}
\usepackage[a4paper,margin=2.5cm]{geometry}
\usepackage{xcolor,booktabs,pgfplots}
\pgfplotsset{compat=1.18}
\usepackage{hyperref,cleveref}
% Stand-ins for the report's macros and colours.
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
    figs = [fig_latency_by_tx(), fig_clients_inside(), fig_serialised(), fig_t7_variants(),
            fig_b16_hist(), fig_absorption()]
    (D / "figures.tex").write_text(
        "% Generated by analysis/task4/narrative_figures.py from analysis/task4/narrative/*.csv.\n"
        "% Do not edit numbers by hand; rerun the script.\n\n" + STYLE + "\n" + "\n".join(figs),
        encoding="utf-8")
    (D / "figures_preview.tex").write_text(PREVIEW, encoding="utf-8")
    print(f"wrote {len(figs)} figures to {D / 'figures.tex'}")


if __name__ == "__main__":
    main()
