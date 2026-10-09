"""Reproduce figures for expt_a0 and its three parameter experiments."""
import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
NAMES = ['a0', 'a0_1', 'a0_2', 'a0_3']
LABELS = ['a0: baseline', 'a0_1: 2 workers', 'a0_2: 80% hot orders', 'a0_3: scale 2']
COLORS = ['#0072B2', '#D55E00', '#009E73', '#CC79A7']
MARKERS = ['o', 's', '^', 'D']
data = {}
for name in NAMES:
    dirs = list((ROOT / f'expt_{name}' / 'slurm-results').glob('job-*/benchmark-results'))
    assert len(dirs) == 1
    path = dirs[0]
    with (path / 'summary.csv').open() as f:
        summary = list(csv.DictReader(f))
    with (path / 'transaction_metrics.csv').open() as f:
        tx = list(csv.DictReader(f))
    data[name] = (summary, tx)

plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                     'pdf.fonttype': 42, 'ps.fonttype': 42})
def save(fig, name):
    fig.savefig(OUT / f'{name}.pdf', bbox_inches='tight')
    fig.savefig(OUT / f'{name}.png', dpi=200, bbox_inches='tight')
    plt.close(fig)

fig, ax = plt.subplots(figsize=(7.5, 4.2), layout='constrained')
for name, label, color, marker in zip(NAMES, LABELS, COLORS, MARKERS):
    rows = data[name][0]
    x = np.array([int(r['clients']) for r in rows])
    y = np.array([float(r['overall_tps']) for r in rows])
    valid = np.array([int(r['pgbench_exit_code']) == 0 for r in rows])
    ax.plot(x, y, color=color, label=label, linewidth=1.7)
    ax.scatter(x[valid], y[valid], color=color, marker=marker, s=45, zorder=3)
    ax.scatter(x[~valid], y[~valid], facecolors='white', edgecolors=color, marker=marker, s=65, linewidths=1.8, zorder=4)
ax.set_xscale('log', base=2)
ax.set_xticks([1,4,8,16,32,64], labels=[1,4,8,16,32,64])
ax.set_xlabel('Clients')
ax.set_ylabel('Successful transactions / configured 600 s (TPS)')
ax.set_ylim(0,4.1)
ax.grid(axis='y', alpha=.22)
handles, labels = ax.get_legend_handles_labels()
handles.append(Line2D([], [], color='#555555', marker='o', markerfacecolor='none', linestyle='none'))
labels.append('Invalid run (pgbench exit code 2)')
ax.legend(handles, labels, loc='lower center', fontsize=9, ncol=2)
save(fig, 'throughput')

fig, ax = plt.subplots(figsize=(7.5, 3.5), layout='constrained')
rows = data['a0'][1]
groups = ['T3', 'T4', 'T6', 'T7', 'Other']
colors = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#999999']
shares = []
for c in [1,64]:
    rr = [r for r in rows if int(r['clients']) == c]
    totals = {r['transaction']: int(r['successful_transactions']) * float(r['avg_latency_ms']) for r in rr}
    denom = sum(totals.values())
    shares.append([100*totals[g]/denom if g != 'Other' else 100*sum(v for k,v in totals.items() if k not in groups)/denom for g in groups])
left = np.zeros(2)
for i,(g,color) in enumerate(zip(groups, colors)):
    widths = np.array([s[i] for s in shares])
    ax.barh([0,1], widths, left=left, color=color, label={'T3':'T3: order history', 'T4':'T4: product lookup', 'T6':'T6: global sales', 'T7':'T7: inventory transfer', 'Other':'Other transactions'}[g])
    for j,w in enumerate(widths):
        if w > 8:
            ax.text(left[j]+w/2,j,f'{w:.1f}%',ha='center',va='center',color='white',fontweight='bold')
    left += widths
ax.set_yticks([0,1], labels=['1 client','64 clients'])
ax.invert_yaxis()
ax.set_xlim(0,100)
ax.set_xlabel('Share of summed successful-transaction latency (%)')
ax.legend(loc='upper center', bbox_to_anchor=(.5,-.23), ncol=3, fontsize=9, frameon=False)
save(fig, 'a0_latency_share')

for name in NAMES:
    print(name)
    for r in data[name][0]:
        print(' & '.join([r['clients']]+[f"{float(r[k]):.3f}" for k in ['overall_tps','overall_median_latency_ms','overall_p95_latency_ms','overall_p99_latency_ms']])+(' INVALID' if int(r['pgbench_exit_code']) else ''))
