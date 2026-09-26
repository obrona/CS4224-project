#!/usr/bin/env bash
#SBATCH --job-name=citus-explain
#SBATCH --nodes=5
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --output=citus-explain-%j.out
#SBATCH --error=citus-explain-%j.err
#SBATCH --partition=normal
#SBATCH --time=03:00:00
#SBATCH --mail-type=BEGIN,END,FAIL
# don't run on nodes with arm processor / ubuntu 26.04
# temporarily exclude xcnc13 as server is problematic
#SBATCH --exclude=xcng0,xcng1,xgpj0,xcnh[0-3],xcnc13

# Records EXPLAIN plans for experiments whose run.sh predates explain/.
# Submit from the repo root, one job per series, pinned like the benchmarks:
#
#   source .env && sbatch --nodelist='xcnf[1,3-6]' --mail-user="$NOTIFY_EMAIL" \
#     explain_plans/run.sh expt_a0 expt_a1 ... expt_a7
#
# Each experiment's run.sh is used unmodified except that its final benchmark
# invocation is replaced by expt_b7's explain_transactions step. It sets up the
# cluster, loads the data and writes the plans to expt_XN/explain/job-<id>/,
# never to slurm-results/. SCALE is passed through from the environment.

set -euo pipefail

info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() {
	echo "ERROR: $*" >&2
	exit 1
}

(($# > 0)) || fail "Usage: sbatch explain_plans/run.sh expt_XN [expt_XN ...]"
[[ -n "${SLURM_JOB_ID:-}" ]] || fail "Run with sbatch or inside a Slurm allocation"
[[ -n "${TEAM_ID:-}" ]] || fail "TEAM_ID is not set; source .env, which must export it"
# expt_a0 and expt_b1 ignore PGPORT, so an override would give the experiments
# different ports and the free-port check below would test the wrong one.
[[ -z "${PGPORT:-}" ]] || fail "Unset PGPORT; every experiment must use the TEAM_ID port"

# The last two lines of every A/B run.sh. They are replaced, never searched for.
TAIL_BENCHMARK='run_benchmark &>"${BENCHMARK_LOG_FILE}"'
TAIL_COMPLETE='info "Experiment complete: $JOB_RESULT_DIR"'

### validate every experiment before doing any work
declare -a EXPTS=()
for arg in "$@"; do
	[[ -d "$arg" ]] || fail "Not a directory: $arg"
	dir=$(cd "$arg" && pwd -P)
	[[ -f "$dir/run.sh" ]] || fail "Missing $dir/run.sh"
	for i in 1 2 3 4 5 6 7 8 9; do
		matches=("$dir"/explain/T${i}_*.sql)
		[[ -f "${matches[0]}" ]] || fail "Missing $dir/explain/T${i}_*.sql"
		((${#matches[@]} == 1)) || fail "More than one $dir/explain/T${i}_*.sql"
	done
	[[ -z "$(tail -c 1 "$dir/run.sh")" ]] || fail "$dir/run.sh does not end with a newline"
	[[ "$(tail -n 2 "$dir/run.sh")" == "$TAIL_BENCHMARK"$'\n'"$TAIL_COMPLETE" ]] ||
		fail "$dir/run.sh does not end with the expected benchmark invocation:
  $TAIL_BENCHMARK
  $TAIL_COMPLETE"
	grep -q '^reset_benchmark_sequences()' "$dir/run.sh" ||
		fail "$dir/run.sh does not define reset_benchmark_sequences, which T1's explain needs"
	! grep -q '^explain_transactions()' "$dir/run.sh" ||
		fail "$dir/run.sh already records plans; submit it directly"
	EXPTS+=("$dir")
done

### the same values run.sh derives; it hard-codes the data dir and port
PGUSER="${SLURM_JOB_USER:-${USER}}"
DATA_ROOT="/tmp/${PGUSER}/citus-${SLURM_JOB_ID}"
PGPORT_USED=$((10#${TEAM_ID} + 5432))
PG_ISREADY="$HOME/pgsql/bin/pg_isready"
[[ -x "$PG_ISREADY" ]] || fail "$PG_ISREADY not found or not executable"
mapfile -t NODES < <(scontrol show hostnames "$SLURM_JOB_NODELIST")

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

on_node() {
	local n="$1"
	shift
	srun --overlap --exact --nodes=1 --ntasks=1 --cpus-per-task=1 --nodelist="$n" "$@"
}

### make sure the previous experiment's servers are gone, then remove its data
# run.sh's cleanup() stops every server with pg_ctl stop -m fast. If that times
# out, it kills the srun steps, and the port frees a few seconds later.
# pg_isready exits 2 when nothing answers; 0 or 1 means a postmaster is there.
reset_nodes() {
	local n rc waited
	for n in "${NODES[@]}"; do
		waited=0
		while :; do
			rc=0
			"$PG_ISREADY" -h "$n" -p "$PGPORT_USED" -U "$PGUSER" -d postgres >/dev/null 2>&1 || rc=$?
			((rc == 2)) && break
			((rc == 0 || rc == 1)) || fail "pg_isready -h $n -p $PGPORT_USED exited $rc"
			((waited++ < 30)) || return 1
			sleep 1
		done
	done
	# init_node in run.sh also removes it; this is done only once nothing is running.
	for n in "${NODES[@]}"; do
		on_node "$n" rm -rf -- "$DATA_ROOT" || fail "Could not remove $DATA_ROOT on $n"
	done
}

### run.sh without the benchmark, plus expt_b7's explain step
build_derived() {
	local src="$1" out="$2" lines
	lines=$(wc -l <"$src")
	head -n $((lines - 2)) "$src" >"$out"
	cat >>"$out" <<'EXPLAIN'
#####################  Explain transactions (appended by explain_plans/run.sh)
# Defined as in expt_b7/run.sh; this run.sh predates explain/.
EXPLAIN_DIR="${SCRIPT_DIR}/explain"

# Record the plan of every statement T1-T9 runs, once, on the freshly loaded
# data and outside the timed benchmark.
explain_transactions() {
	local f
	reset_benchmark_sequences # T1 draws from benchmark_order_id_seq
	for f in "$EXPLAIN_DIR"/T*.sql; do
		echo "==================== $(basename "$f")"
		if ! psqlx -v REPORT_DAYS="$REPORT_DAYS" -f "$f" >/dev/null ||
			! psqlx -v REPORT_DAYS="$REPORT_DAYS" --echo-queries --no-align --tuples-only -f "$f"; then
			echo "FAILED: $(basename "$f")"
			wait_for_coordinator 120 || return 1
		fi
	done
}
wait_for_coordinator() {
	local timeout="$1" waited=0
	until "${PG_BIN_DIR}/pg_isready" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres >/dev/null 2>&1; do
		((waited++ < timeout)) || { echo "Coordinator not ready after ${timeout}s"; return 1; }
		sleep 1
	done
}
# expt_b7 swallows a failure here with `|| echo`. This run exists only for the
# plans, so the exit status is kept for the driver.
explain_transactions &>"$JOB_RESULT_DIR/explain.log"
info "Explain complete: $JOB_RESULT_DIR"
EXPLAIN
}

info "SLURM_JOB_ID=$SLURM_JOB_ID nodes=${NODES[*]} port=$PGPORT_USED SCALE=${SCALE:-unset (run.sh uses 1)}"

declare -a FAILED=()
declare -a NOT_RUN=()
for idx in "${!EXPTS[@]}"; do
	dir="${EXPTS[idx]}"
	name=$(basename "$dir")

	if ! reset_nodes; then
		# Starting another run.sh would reuse the port of a server we could not
		# stop, so neither this nor any later experiment can run safely.
		echo "ERROR: a server still answers on port $PGPORT_USED before $name" >&2
		NOT_RUN=("${EXPTS[@]:idx}")
		break
	fi

	info "==== $name"
	derived="$WORK_DIR/$name.sh"
	build_derived "$dir/run.sh" "$derived"
	rc=0
	(cd "$dir" && SCRIPT_DIR="$dir" RESULT_ROOT="$dir/explain" bash "$derived") || rc=$?

	# Fallback: one experiment failing (non-zero exit, or a FAILED: script in its
	# explain.log) does not stop the others. Each run.sh builds its own cluster
	# from an empty data dir, and reset_nodes confirms the old servers are gone,
	# so a failure cannot leak into the next experiment; the job still exits 1.
	log="$dir/explain/job-$SLURM_JOB_ID/explain.log"
	if ((rc != 0)); then
		FAILED+=("$name: run exited $rc")
		continue
	fi
	grep_rc=0
	grep -q '^FAILED:' "$log" || grep_rc=$?
	case "$grep_rc" in
	0) FAILED+=("$name: $(grep '^FAILED:' "$log" | tr '\n' ' ')") ;;
	1) info "$name: plans in $log" ;;
	*) fail "Cannot read $log" ;;
	esac
done

if ((${#NOT_RUN[@]} == 0)) && ! reset_nodes; then
	FAILED+=("cleanup: a server still answers on port $PGPORT_USED after the last experiment")
fi

info "==== Summary"
for f in "${FAILED[@]}"; do echo "FAILED  $f"; done
for d in "${NOT_RUN[@]}"; do echo "NOT RUN $(basename "$d")"; done
((${#FAILED[@]} == 0 && ${#NOT_RUN[@]} == 0)) || exit 1
info "All ${#EXPTS[@]} experiments recorded their plans"
