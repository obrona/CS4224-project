### Prev: expt_a8

T1 is rewritten as one set-based statement of chained CTEs that checks stock,
reserves it and inserts the order and its items together, instead of up to 26
separate statements per order. This is the same change as `expt_b9`, and the
transactions are identical to `expt_b9`'s.

Provenance: this run is cell `expt_a300` (set-based T1, no other factor) of the
workload-A ablation grid, job 908401, renamed to `expt_a9` on main with its code
unchanged; the grid is in git history at `4ed72d57`. `expt_a7` and `expt_a8` ran
on `xcnf[1,3-6]`, while this run and the rest of the chain ran on
`xcnf[0-2,4,5]`, so the step from `expt_a8` also changes the node set.
