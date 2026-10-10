### Prev: expt_a9

T7 is routed through a new `product_merchant_map` table, distributed by
`product_id`: T7 looks up each product's merchant and then debits and credits
with single-shard `UPDATE`s, instead of sending each statement to all 32
inventory shards. This is the same change as `expt_b10`, and the transactions
are identical to `expt_b10`'s.

Provenance: this run is cell `expt_a304` of the workload-A ablation grid, job
909385, renamed to `expt_a10` on main with its code unchanged; the grid is in
git history at `4ed72d57`.
