### Prev: expt_a10

T5 is routed through a new `order_merchant_map` table, distributed by
`order_id` and written by T1 for each new order: T5 looks up the order's
merchant and updates one shard, instead of all 32. This is the same change as
`expt_b11`, and the transactions are identical to `expt_b11`'s.

Provenance: this run is cell `expt_a305` of the workload-A ablation grid, job
909386, renamed to `expt_a11` on main with its code unchanged; the grid is in
git history at `4ed72d57`.
