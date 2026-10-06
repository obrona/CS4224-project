#!/usr/bin/env bash
# Run the workload-B baseline parameter study (expt_b0_1 to expt_b0_7)
# hands-free, as one Slurm dependency chain:
#
#   expt_b0_7 -> push -> expt_b0_1 -> push -> ... -> expt_b0_3 -> push
#
# Each experiment is submitted from its own folder, as run.sh requires
# (it finds transactions/ and writes slurm-results/ relative to
# SLURM_SUBMIT_DIR). Each "push" is a small Slurm job that commits that
# experiment's folder and pushes it to the branch. It runs on a compute node,
# where git has enough memory for the large result logs. Every step waits for
# the previous one with afterany, so the experiments never overlap on their
# shared nodes, and a failed experiment still has its logs committed while
# the chain moves on.
#
# Usage, from the repository root on xlogin, on the b-side branch:
#   ./run_b0_study.sh submit     # check everything, then submit the chain
#   ./run_b0_study.sh status     # what is queued, and the push log so far
#
# NOTIFY_EMAIL and TEAM_ID come from .env, as for a manual sbatch.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="b-side"
# Reference first, then the six variations.
EXPERIMENTS=(expt_b0_7 expt_b0_1 expt_b0_4 expt_b0_2 expt_b0_5 expt_b0_6 expt_b0_3)
LOG_DIR="${HOME}/b0-study-logs"  # outside the repository, so never committed
MAX_FILE_MB=95                   # GitHub rejects files over 100 MB

# Lower git's memory use for packing the result logs.
GIT_LOWMEM=(-c pack.threads=1 -c pack.windowMemory=64m -c pack.deltaCacheSize=32m -c core.bigFileThreshold=16m)

die() { echo "error: $*" >&2; exit 1; }
log() { echo "[$(date '+%F %T')] $*"; }

load_env() {
	if [[ -f "$REPO/.env" ]]; then
		set -a
		# shellcheck disable=SC1091
		source "$REPO/.env"
		set +a
	fi
}

### submit: check, then submit the whole chain
submit() {
	cd "$REPO"
	load_env
	[[ -n "${NOTIFY_EMAIL:-}" ]] || die "NOTIFY_EMAIL is not set; add it to .env"
	[[ -n "${TEAM_ID:-}" ]] || die "TEAM_ID is not set; add it to .env"

	[[ "$(git rev-parse --abbrev-ref HEAD)" == "$BRANCH" ]] ||
		die "check out $BRANCH first (currently on $(git rev-parse --abbrev-ref HEAD))"
	git diff --cached --quiet || die "there are staged changes; commit or unstage them first"

	local e
	for e in "${EXPERIMENTS[@]}"; do
		[[ -f "$e/run.sh" && -d "$e/transactions" ]] || die "$e is missing run.sh or transactions/"
		[[ ! -d "$e/slurm-results" ]] || die "$e already has slurm-results/; move it away to rerun"
	done

	if squeue -u "$USER" -h -o '%j' | grep -q '^b0-study-push-'; then
		die "a b0-study chain is already queued; see: $0 status"
	fi

	# A push job runs on a compute node, so its git credentials must work
	# there, not only on xlogin. Test that now, not after the first 1.5 h run.
	log "Checking that git can push from a compute node..."
	srun -p normal -N1 -n1 -c1 --mem=2G -t 00:05:00 \
		git -C "$REPO" push --dry-run origin "$BRANCH" ||
		die "git push --dry-run failed on a compute node; fix credentials (e.g. git config credential.helper store) and retry"

	mkdir -p "$LOG_DIR"
	local prev="" jid pid dep
	for e in "${EXPERIMENTS[@]}"; do
		dep=()
		[[ -n "$prev" ]] && dep=(--dependency="afterany:$prev")

		jid=$(cd "$REPO/$e" && sbatch --parsable "${dep[@]}" --mail-user="$NOTIFY_EMAIL" run.sh)
		pid=$(sbatch --parsable --dependency="afterany:$jid" \
			-p normal -N1 -n1 -c1 --mem=4G -t 00:30:00 \
			-J "b0-study-push-$e" -o "$LOG_DIR/push-$e-%j.out" \
			--chdir="$REPO" \
			--wrap="bash '$REPO/run_b0_study.sh' push '$e' '$jid'")
		log "$e: experiment job $jid, push job $pid"
		prev="$pid"
	done
	log "Submitted. Follow it with: $0 status"
}

### push: commit one experiment's results and push them (runs as a Slurm job)
push_results() {
	local e="$1" jid="$2"
	cd "$REPO"
	log "Pushing results of $e (job $jid)"

	# Use the run's own log, not sacct, for the outcome.
	local outcome="FAILED"
	grep -q 'Experiment complete' "$e/citus-$jid.out" 2>/dev/null && outcome="complete"
	local exits
	exits=$(awk -F, 'NR>1 && $13!=0 {printf "%sc%s", sep, $1; sep=","}' \
		"$e"/slurm-results/job-"$jid"/benchmark-results/summary.csv 2>/dev/null || true)
	log "outcome: $outcome; client counts with a nonzero pgbench exit: ${exits:-none}"

	local big
	big=$(find "$e" -type f -size +"${MAX_FILE_MB}"M)
	if [[ -n "$big" ]]; then
		log "not pushing: files over ${MAX_FILE_MB} MB, which GitHub would reject:"
		echo "$big"
		exit 1
	fi

	git "${GIT_LOWMEM[@]}" fetch origin "$BRANCH"
	git merge --ff-only "origin/$BRANCH" || log "warning: could not fast-forward; will rebase before pushing"

	git add -- "$e"
	local msg="Add $e results (job $jid)"
	[[ "$outcome" == "complete" ]] || msg="Add $e results (job $jid, FAILED; logs only)"
	[[ -z "$exits" ]] || msg="$msg; nonzero pgbench exit at $exits"
	if git diff --cached --quiet; then
		log "nothing to commit for $e"
		exit 0
	fi
	git commit -q -m "$msg" -- "$e"
	log "committed: $msg"

	local try
	for try in 1 2 3; do
		if git "${GIT_LOWMEM[@]}" push origin "$BRANCH"; then
			log "pushed (attempt $try)"
			return 0
		fi
		log "push attempt $try failed; rebasing on origin/$BRANCH and retrying"
		git "${GIT_LOWMEM[@]}" pull --rebase origin "$BRANCH" || true
		sleep 30
	done
	log "push failed three times; the commit is kept locally. Push it by hand: git push origin $BRANCH"
	exit 1
}

### status: what is queued, and what has been pushed
status() {
	squeue -u "$USER" -o '%.10i %.30j %.8T %.10M %R' || true
	echo
	if compgen -G "$LOG_DIR/push-*.out" >/dev/null; then
		grep -h -E 'outcome:|committed:|pushed|failed|not pushing' "$LOG_DIR"/push-*.out
	else
		echo "no push jobs have run yet"
	fi
}

case "${1:-}" in
submit) submit ;;
push) push_results "$2" "$3" ;;
status) status ;;
*) die "usage: $0 submit | status" ;;
esac
