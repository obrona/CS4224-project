### Prev: expt_a11

T6 is answered from a new per-merchant, per-day `merchant_daily_sales` rollup,
colocated with `orders` and updated by T1 in the same transaction, so T6 reads
the rollup for whole days and `orders` only for the boundary day. This is the
same change as `expt_b12`, and the transactions are identical to `expt_b12`'s.

Provenance: this run is cell `expt_a307` of the workload-A ablation grid, job
908405, renamed to `expt_a12` on main with its code unchanged; the grid is in
git history at `4ed72d57`.
