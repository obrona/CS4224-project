### Prev: expt_a13

Every distributed table is created with 8 shards (2 per worker) instead of
Citus's default 32, via `CITUS_SHARD_COUNT` (default 8, recorded in
`config.txt`), so all-shard queries such as T6 dispatch 8 tasks instead of 32.
This is the same change as `expt_b14`, and the transactions are identical to
`expt_b14`'s.

Provenance: this run is cell `expt_a331` of the workload-A ablation grid, job
904117, renamed to `expt_a14` on main with its code unchanged; the grid is in
git history at `4ed72d57`. The job predates the grid: it is the rerun of an
earlier experiment then named `expt_a10` (not today's `expt_a10`).
