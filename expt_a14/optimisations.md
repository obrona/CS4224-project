### Prev: expt_a10

This experiment routes T7 (Inventory Transfer) to the shards that hold its two
inventory rows, using a new lookup table `product_merchant_map`. It is a port
of `expt_b4`'s T7 routing onto `expt_a10`: `T7_inventory_transfer.sql` is
identical to `expt_b4`'s and `expt_b7`'s, and the `product_merchant_map`
changes to `run.sh` are `expt_b7`'s. There is no other change to the schema,
data distribution, indexes, the other transactions, or server parameters
carried over from `expt_a10`. `run.sh` also records plans (see "Recording
plans"), outside the timed benchmark.

`expt_a14` and `expt_a15` each add T7 routing to one earlier experiment, so each
difference isolates T7 routing on a different base:

| Experiment | T5 routing | T6 rollup | T1 delegation | T7 routing (this) |
| ---------- | ---------- | --------- | ------------- | ----------------- |
| `expt_a10`  | yes        |           |               |                   |
| `expt_a14`  | yes        |           |               | yes               |
| `expt_a13`  | yes        | yes       | yes           |                   |
| `expt_a15`  | yes        | yes       | yes           | yes               |

`a14 - a10` measures T7 routing with T5 routing only; `a15 - a13` measures it on
the final design.

### Motivation

T7's average latency (ms):

| Experiment | 1 client | 8 clients | 64 clients |
| ---------- | -------- | --------- | ---------- |
| `expt_a9`  | 31.0     | 83.9      | 215.2      |
| `expt_a10`  | 30.8     | 86.1      | 2834.1     |
| `expt_a13`  | 33.6     | 57.6      | 1364.0     |

T7's share of total measured latency (`avg_latency_ms` x
`successful_transactions`, over the workload total):

| Experiment | 1 client | 8 clients | 64 clients |
| ---------- | -------- | --------- | ---------- |
| `expt_a10`  | 14.9%    | 19.4%     | 84.3%      |
| `expt_a13`  | 25.1%    | 30.7%     | 89.8%      |

T7 is 5% of workload A, yet once `expt_a10` routed T5 it became the bottleneck
at 64 clients, as T5 did on the B side once `expt_b4` routed T7. The T7
statements are the same in `expt_a9` and `expt_a10`, but at 64 clients T7 went
from 215.2 ms to 2834.1 ms. In `expt_a10` at 64 clients T7 runs at 19.055 TPS,
so by Little's law 19.055 x 2.834 = 54 of the 64 clients are inside T7 at any
moment, and 19.055 / 0.05 = 381 TPS is the observed overall throughput
(377.1). `expt_a13` gives the same picture: 42.140 x 1.364 = 57 clients in T7,
and 42.140 / 0.05 = 843 TPS against 838.9 observed.

On the B side, `expt_b4` made this change on top of `expt_b3`. T7's average
latency went from 32.4 to 4.4 ms at 1 client, 84.8 to 8.2 ms at 8 clients, and
860.6 to 9.0 ms at 64 clients, and overall throughput at 64 clients from 239.8
to 367.1 TPS.

### Why T7 is slow

T7 is given only `source_product_id`, `dest_product_id` and `transfer_qty`,
while `inventory` is distributed by `merchant_id`. None of its six statements
(two `EXISTS` probes, two `SELECT inventory_id` lookups by `product_id`, and
the debit and credit `UPDATE`s by `inventory_id`) names `merchant_id`, so
Citus sends each one to all 32 `inventory` shards, inside a `SERIALIZABLE`
transaction. Both `UPDATE`s therefore take part on every worker, and every
worker joins every T7's commit, whichever two rows change.

The recorded plan shows this. In
`git show explain-plans:expt_a13/explain/job-883041/explain.log` (job 883041,
on `xcnf[1,3-6]`), every one of the six statements in the T7 section has
`Task Count: 32`. On each shard, no index leads with the column T7 filters on:
the lookups by `product_id` skip-scan `UNIQUE (merchant_id, product_id)` and
the updates by `inventory_id` skip-scan `inventory_pkey`
`(merchant_id, inventory_id)`, with 12 to 18 `Index Searches` per shard in the
sample shards shown. `expt_a10` runs the same T7 statements as `expt_a13`, so
the same plan applies here.

### Optimisation: product_merchant_map and routed T7

The design and its argument are in `expt_b4/optimisations.md` and carry over
unchanged. In short:

- `product_merchant_map (product_id PRIMARY KEY, merchant_id)` is distributed
  by `product_id` with `colocate_with => 'none'`, so a lookup by product id
  goes to one shard. `generate_data` fills it from `products` straight after
  `products` and `inventory` are loaded, and it is in the `TRUNCATE` list, so
  every reset rebuilds it.
- T7 looks up both merchants with
  `SELECT COALESCE(MAX(merchant_id), 0) ... \gset t7_`, **before** `BEGIN`. A
  product's merchant never changes and no transaction writes the map (nothing
  inserts products, T9 changes only `price`), so reading it outside the
  transfer cannot give a different answer than reading it inside. Keeping it
  outside also keeps the map shards' workers out of T7's distributed
  transaction: only the one or two workers holding the changed rows join the
  commit.
- The debit and credit `UPDATE`s filter on
  `merchant_id = :t7_*_merchant_id AND product_id = ...`, so each goes to one
  shard and uses the `UNIQUE (merchant_id, product_id)` index. The four probes
  are gone: a missing inventory row makes its `UPDATE` affect zero rows, which
  already rolls the transfer back.
- On a miss (`merchant_id = 0`) T7 falls back to `expt_a10`'s un-routed
  statements. It is unreachable here: T7 draws both products from
  `1..NUM_PRODUCTS`, `products` holds exactly that range, and the map is a copy
  of `products`. It is kept so that a stale map gives a slow answer instead of
  silently skipping a transfer through `WHERE merchant_id = 0`.

Per transfer this goes from 6 statements x 32 shards, with all 4 workers in
the commit, to 2 single-shard lookups and 2 single-shard `UPDATE`s, with 1 or
2 workers in the commit. The source and destination are independent draws, so
about 3 in 4 transfers still commit across two workers.

### Credit: independent implementation on branch `tl`

A teammate implemented T7 routing independently on branch `tl`
(`git show origin/tl:expt_a12/optimisations.md` and
`origin/tl:expt_a12/transactions/T7_inventory_transfer.sql`), with a locator
table `product_route(product_id, inventory_id, merchant_id)` distributed by
`product_id`. The designs differ in two ways:

- `tl` looks up `product_route` **inside** the transaction, so the workers
  holding the locator shards join T7's distributed transaction. `expt_b4`'s
  version does the lookups before `BEGIN`.
- `tl` also stores `inventory_id` and filters the `UPDATE`s on it together
  with `merchant_id` and `product_id`. `UNIQUE (merchant_id, product_id)`
  already identifies the row, so `inventory_id` is redundant there.

`tl` also rolls back on a missing locator row, where `expt_b4`'s version falls
back to the un-routed statements.

This experiment uses `expt_b4`'s version because it has already been run on
this schema and keeps the lookups out of the transaction. `tl`'s results are
not compared here: they were measured on different, unpinned nodes.

### Recording plans

After data generation, `run.sh` writes `explain.log` with the plan of every
statement T1 to T9 runs, as `expt_b6` and `expt_b7` do; the `explain/` scripts
and the step itself are described in `expt_b6/optimisations.md`. The scripts
here are the A-side ones recorded in job 883041 for `expt_a10`, with T7 replaced
by `expt_b7/explain/T7_inventory_transfer.sql`. Each follows the routed path
of this experiment's own transaction with its variables substituted. A change
to a transaction must be copied into its explain script.

### What to look at when this is run

- **T7 latency at 64 clients**, 2834.1 ms in `expt_a10`. A T7 p99 anywhere near
  `expt_a10`'s p50 (2807.6 ms) would mean the fallback is firing.
- **T1, T5 and T6** should not change beyond noise against `expt_a10`: T7
  routing touches none of their statements.
- **`pgbench_exit_code`, `failed_log_records`, `serialization_failures` and
  `deadlock_failures`.** T7 debits before it credits, so two opposite
  transfers between the same two products can deadlock across workers, and T7
  should now run far more often.
- **The next bottleneck.** Recompute the latency-share table.
- **`explain.log`.** The T7 section should show `Task Count: 1` for each
  lookup and each `UPDATE`.
- **Comparability.** Pinned to `xcnf[1,3-6]`, the same nodes as `expt_a0` to
  `expt_a13`. Check that T2, T3, T4, T8 and T9 land within about 2% of
  `expt_a10` at 1 client before attributing any delta. `expt_a10` to `expt_a13`
  ran as four concurrent jobs on these nodes; if this runs alongside
  `expt_a15` only, the load from other jobs differs, which that check is
  meant to catch.
