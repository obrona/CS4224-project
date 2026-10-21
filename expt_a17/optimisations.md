### Prev: expt_a15

Order ids are chosen so that T1's `order_merchant_map` row lands on the
merchant's worker. `order_merchant_map` is distributed with
`colocate_with => 'merchants'` instead of `'none'` (both `bigint`, 4 shards,
so shard i of each is on the same node), and T1 draws its order id from a new
coordinator-local function `public.next_colocated_order_id(merchant_id)`,
which pulls ids from `benchmark_order_id_seq` until one hashes to an
`order_merchant_map` shard placed on the node that holds the merchant's
shards (it raises after 1000 draws). The function is not distributed. T5
routing is kept unchanged; only `place_order`'s step-7 comment changes.

Expected to remove: the two-phase commit on every T1. In `expt_a15` the
step-7 insert usually goes to another worker, so the delegated call commits
across two nodes; here all of `place_order`'s writes are on one worker. The
price is a few extra `nextval` and shard lookups on the coordinator per T1
(about 4 draws on average with 4 workers) and gaps in new order ids, which
nothing relies on (T5 draws only from the initial orders).

Run: job 972056, team id 304, on `xcnf[0-2,4,5]`, in the same batch as `expt_a16`, `expt_a17`, `expt_a20` and `expt_a21` (jobs 972055 to 972058).
