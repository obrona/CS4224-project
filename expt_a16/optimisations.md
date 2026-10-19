### Prev: expt_a15

`expt_a15` without T5 routing: `order_merchant_map` is gone (table, its
distribution, its initial fill and its `TRUNCATE` entry), `place_order` no
longer writes it (step 7 removed), and T5's transaction and explain files are
the unrouted ones, byte-identical to `expt_a10`'s, so T5 updates `orders` by
`order_id` alone across all shards. Nothing else changes.

Why: ablation of T5 routing on top of the delegated T1. Since `expt_a15`
places T1 on the merchant's worker, step 7 is T1's only write off that worker,
so routing T5 costs every T1 a two-phase commit; this run measures what T5
routing is worth once that cost is counted.

Run: job 972055, team id 204, on `xcnf[0-2,4,5]`, at the same time as the other five jobs of this batch (972053 to 972058).
