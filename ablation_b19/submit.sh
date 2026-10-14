#!/bin/bash
# Submit expt_b27 .. expt_b46 as one chain: each job starts only after the
# previous one has ended (afterany), so no two share xcnf[17-21]. Cells go in
# priority order: one factor off, two off, three off, all off, then the shard
# counts 1, 2, 8, 16, 32. Each job id is appended to ablation_b19/run_order.csv.
#
#   bash ablation_b19/submit.sh                 # submit expt_b27 .. expt_b46
#   bash ablation_b19/submit.sh 42              # resume from expt_b42
#   bash ablation_b19/submit.sh 42 123456       # ... starting after job 123456
set -euo pipefail

cd "$(dirname "$0")/.."
first="${1:-27}"
prev="${2:-}"
order=ablation_b19/run_order.csv
[[ -f "$order" ]] || echo "experiment,slurm_job" >"$order"

for n in $(seq "$first" 46); do
	d="expt_b$n"
	[[ -f "$d/run.sh" ]] || { echo "missing $d/run.sh" >&2; exit 1; }
	if [[ -d "$d/slurm-results" ]]; then
		echo "$d already has slurm-results/; not resubmitting it" >&2
		exit 1
	fi
	jid=$(cd "$d" && sbatch --parsable ${prev:+--dependency=afterany:$prev} run.sh)
	prev="${jid%%;*}"
	echo "$d,$prev" | tee -a "$order"
done
