#!/bin/bash
# Submit the partitioning batch as one chain: each job starts only after the
# previous one has ended (afterany), so no two share xcnf[17-21]. The batch
# starts and ends with a replicate of the final design expt_b19:
#   expt_b20, expt_b22, expt_b23, expt_b24, expt_b25, expt_b21
# Each job id is appended to partitioning_b19/run_order.csv.
#
#   bash partitioning_b19/submit.sh                    # submit the whole batch
#   bash partitioning_b19/submit.sh expt_b23           # resume from expt_b23
#   bash partitioning_b19/submit.sh expt_b23 123456    # ... starting after job 123456
set -euo pipefail

cd "$(dirname "$0")/.."
batch=(expt_b20 expt_b22 expt_b23 expt_b24 expt_b25 expt_b21)
first="${1:-${batch[0]}}"
prev="${2:-}"
order=partitioning_b19/run_order.csv
[[ -f "$order" ]] || echo "experiment,slurm_job" >"$order"

started=0
for d in "${batch[@]}"; do
	[[ "$d" == "$first" ]] && started=1
	((started)) || continue
	[[ -f "$d/run.sh" ]] || { echo "missing $d/run.sh" >&2; exit 1; }
	if [[ -d "$d/slurm-results" ]]; then
		echo "$d already has slurm-results/; not resubmitting it" >&2
		exit 1
	fi
	jid=$(cd "$d" && sbatch --parsable ${prev:+--dependency=afterany:$prev} run.sh)
	prev="${jid%%;*}"
	echo "$d,$prev" | tee -a "$order"
done
((started)) || { echo "$first is not in the batch: ${batch[*]}" >&2; exit 1; }
