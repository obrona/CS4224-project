# Workload-B what-if partitioning around expt_b19

The final design `expt_b19` (`SERIALIZABLE`, 4 shards) distributes every tenant
table by `merchant_id`. Two transactions pay for that: T7 (30% of workload B)
moves stock between two random products and needs a lookup to find each row's
merchant, and T5 (10%) is given only an `order_id` and needs
`order_merchant_map`, which every T1 writes on a second worker. Each experiment
here places one group of tables differently to remove one of those costs,
everything else being `expt_b19`'s.

| Cell | Placement | Removes | Costs | Compare with |
| ---- | --------- | ------- | ----- | ------------ |
| `expt_b22` | `products` + `inventory` by `product_id` | T7's lookup | T1 spans workers, not delegated | ablation's T1-off cell, `expt_b19` |
| `expt_b23` | `orders` + `order_items` by `order_id` | T5's lookup, `order_merchant_map` | T3 asks every shard | ablation's T5-off cell, `expt_b19` |
| `expt_b24` | `products` + `inventory` as colocated single-shard tables (one node) | T7's lookup and its cross-worker commit | every catalog access on one worker | ablation's T1-off cell, `expt_b19` |
| `expt_b25` | `inventory` as a reference table | T7's lookup | every inventory write to all 5 nodes | ablation's T1-off cell, `expt_b19` |

`expt_b22`, `expt_b24` and `expt_b25` move the merchant's inventory off its
worker, so T1 there is `expt_b8`'s multi-statement T1 with the map insert and
rollup upsert, the same T1 as the ablation cell around `expt_b19` with only T1
delegation off; a delegated `place_order` would open a new connection for
every remote statement (`expt_b16`). That ablation cell therefore isolates the
placement, and `expt_b19` gives the design as a whole. `expt_b23` keeps the
delegated T1 without the map insert, the T1 of the ablation's T5-routing-off
cell. Each cell's `optimisations.md` lists every change.

The forced changes are: `inventory`'s keys lead with `product_id` where T7
finds rows by `product_id` (b22, b24, b25); `order_items`' primary key includes
`order_id` (b23), since Citus requires the distribution column in every
primary key; and where `products` or `orders` leave merchant colocation (b22,
b23, b24) the data load computes each item's `unit_price` with the formula that
generated `products.price` instead of joining `products`, which gives the same
rows.

These cells were first built around the `REPEATABLE READ` design (as
`expt_b38` .. `expt_b41`, never run). Rebuilt around `expt_b19`, their code
differs from that version only in `run.sh` line 70, the isolation level.

## Batch

The cells run in one `afterany` chain between two replicates of `expt_b19`, so
the batch has a same-period reference at both ends:

```text
expt_b20 (replicate)  expt_b22  expt_b23  expt_b24  expt_b25  expt_b21 (replicate)
```

## Use

```sh
python3 partitioning_b19/generate.py           # (re)write expt_b22 .. expt_b25
python3 partitioning_b19/generate.py --check   # verify them; exits 1 on any difference
bash partitioning_b19/submit.sh                # submit the batch as one afterany chain
bash partitioning_b19/submit.sh expt_b23 <job> # resume from expt_b23, after job <job>
```

`generate.py` builds on `ablation_b20/generate.py`'s helpers (pointing them at
`expt_b19`), so it needs that folder and `expt_b19`/`expt_b8`. It refuses to
overwrite a cell that already has `slurm-results/`. `expt_b20` and `expt_b21`
are plain copies of `expt_b19`'s `run.sh`, `transactions/` and `explain/`.

These layouts change the schema and the data load, which no earlier run has
exercised. Before the full chain, a short run of each (for example
`cd expt_b22 && DURATION=60 WARMUP_DURATION=10 CLIENT_COUNTS="4" sbatch run.sh`)
shows within minutes whether `schema-create.log`, `data-generation.log` and
`explain.log` are clean and how long a reload takes (the job has a 3-hour
limit and reloads before every client count). Delete that run's
`slurm-results/` and `citus-*.out`/`.err` before submitting the chain, which
refuses cells that have `slurm-results/`.
