### Prev: expt_a12

T1 moves into a distributed function, `place_order`, which Citus delegates
whole to the worker holding the merchant's shards, instead of running T1's CTE
statement as separate distributed subplans through the coordinator. This is the
same change as `expt_b13`, and the transactions are identical to `expt_b13`'s.

Provenance: this run is cell `expt_a323` of the workload-A ablation grid, job
904119, renamed to `expt_a13` on main with its code unchanged; the grid is in
git history at `4ed72d57`. The job predates the grid: it was run as a control
rerun of the code of an earlier experiment then named `expt_a9` (not today's
`expt_a9`).
