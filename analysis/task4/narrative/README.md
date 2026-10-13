# Workload-B narrative data pack (Section 5, experiments onward)

> **Superseded by [`pack/README.md`](../pack/README.md)** (2026-10-13), the evidence pack for Section 5,
> which covers every run up to `expt_b46`. Kept for the analyses it describes in more detail.

> **Renumbered 2026-10-11.** The `REPEATABLE READ` run described here as `expt_b20` is now
> `expt_b26` (not carried forward); `expt_b19` is the final design. `expt_b20`/`expt_b21` are
> new replicates of `expt_b19` and `expt_b22`..`expt_b25` the partitioning cells. The CSVs
> use the new names; the prose below still uses the old ones.

Source material for the rewritten Section 5. It follows the new storyline:

1. **Try workload A's design first** (`expt_b7`, `expt_b8`): far faster than expected, but T7 is left behind.
2. **Adapt it to B** (`expt_b10`): `product_merchant_map` is safe because nothing changes a product's merchant after loading.
3. **Converge with A** (`expt_b11`..`expt_b15`): the same steps as the A side, covered briefly here and in full in the A section.
4. **B-specific work on T7** (`expt_b16`..`expt_b19`, then `expt_b20`): T7 is 30% of the mix, so small cuts to it are tried.

Everything here is computed from the runs. `../README.md` (the earlier pack) remains the reference
for definitions, job numbers and the full TPS table; this pack adds figure data, raw-log analyses
and some new findings. Regenerate with:

```
python3 analysis/task4/collect.py              # chain CSVs (unchanged)
python3 analysis/task4/collect_narrative.py    # this folder's CSVs (~90 s, reads every pgbench log)
python3 analysis/task4/narrative_figures.py    # figures.tex from the CSVs
cd analysis/task4/narrative && latexmk -pdf figures_preview.tex
```

`figures.tex` holds six ready figures in the report's style (colours `bcA`..`bcInert`, macros
`\expt`, `\txn`, `\tbl`, `\code`). Paste the `\pgfplotsset{narr/...}` block once, then any
figure. `figures_preview.pdf` shows them compiled.

---

## Beat 1: workload A's design on workload B (b7, b8)

**The surprise, in numbers.** Mean TPS goes from 7.05 (b0) to 10.99 (b7, 1.56x) to 199.8 (b8,
18.2x): **28.3x over b0 after two steps**, and 37.2x at 64 clients (6.38 -> 237.1 TPS).

**Figure A, `fig:b-a-design-latency`** (`latency_by_tx.csv`): mean latency per transaction at 1
client for b0, b7, b8, log scale.

| Transaction (weight) | b0 | b7 | b8 |
| --- | ---: | ---: | ---: |
| T3 Order History (5%) | 1,944.6 ms | 1,872.9 | **1.44** |
| T4 Product Lookup (5%) | 362.0 | **0.97** | 0.98 |
| T6 Global Sales (10%) | 199.3 | 43.0 | 44.1 |
| T7 Inventory Transfer (30%) | 36.2 | 30.3 | 32.5 |
| T5 Update Order Status (10%) | **1.38** | 6.30 | 6.73 |

**A new point for the text: colocation is a trade-off, not a free win.** b0 distributed `orders`
by `order_id` and `inventory` by `inventory_id` (`expt_b0/run.sh` lines 451-452). Under those
keys, T5's `UPDATE orders ... WHERE order_id`, T1's final `UPDATE orders ... WHERE order_id` and
T7's `UPDATE inventory ... WHERE inventory_id` each went to **one** shard. Distributing by
`merchant_id` sends all three to **every** shard. That is why T5 gets 4.6x slower at 1 client
(1.38 -> 6.30 ms). The two lookup maps of b10/b11 win back that single-shard routing while
keeping colocation.

**Mechanism (new, confirmed in Citus source): multi-shard `UPDATE`s queue one at a time.**
Citus 14.1.0, `src/backend/distributed/executor/distributed_execution_locks.c`, lines 88-137
(`AcquireExecutorShardLocksForExecution`). A modification that runs on more than one shard
takes `ShareUpdateExclusiveLock` on every shard it touches. That lock conflicts with itself:
"only one multi-shard modification at a time is allowed on a shard". The GUC that controls this,
`citus.enable_deadlock_prevention`, defaults to `true` (`shared_library_init.c`), and no run
changes it. The lock is transaction-scoped (`LockShardResource`, `sessionLock = false`,
`utils/resource_lock.c` line 667), so it is held until `COMMIT`. Single-shard modifications skip
it. This one rule explains three bottlenecks (**Figure C, `fig:b-serialised`**,
`tx_by_clients.csv`):

| Where | Evidence |
| --- | --- |
| b7, `orders` | T1's final `UPDATE orders` (no `merchant_id`, `expt_b7/transactions/T1_place_order.sql` line 431) and T5 share one queue. Their latencies match at every client count: 225 / 226 ms at 16 clients, 2,081 / 2,168 at 32, **12,538 / 12,545 at 64**. b8 adds `merchant_id` to T1's `UPDATE`, and both fall to 8.5 / 9.5 ms at 64. |
| b8, b9, `inventory` | T7 completes **64.8-71.2 times per second from 4 to 64 clients**, whatever the load, while its latency grows with clients (36.7 -> 861.5 ms). It holds 61.3 of the 64 clients (97.0% of latency). |
| b10, `orders` | T5's code is unchanged since b8. It completes **35.5-36.3 times per second from 8 clients on** and holds 56.7 of the 64 clients. Its latency at 64 goes from 9.7 ms (b9) to 1,561.7 ms (b10). |

Why T7 cannot benefit from colocation: products are uniform over merchants
(`merchant = 1 + (product_id - 1) % 1000`). The two products are from the same merchant with
probability 1/1000. Using Citus's hash, they sit on **different workers 74.9% of the time with
32 shards, 74.9% with 8 and 75.0% with 4** (`placement.csv`). That is the exact value behind
"three times in four". The hash port was checked against six (merchant, shard, worker)
placements in the plans.

In b8, T7 issues 6 data statements (2 `EXISTS`, 2 `SELECT inventory_id`, 2 `UPDATE`). None
names `merchant_id`, so each goes to all 32 shards: 192 shard tasks per T7. The two `UPDATE`s
take the shard lock above on all 32 `inventory` shards until `COMMIT`.

## Beat 2: adapting to B with `product_merchant_map` (b10)

**Why it is safe.** No transaction inserts or deletes products or changes `products.merchant_id`:

- T9, the only writer of `products`, sets `price` only (`T9_update_product.sql`).
- T1, T2 and T7 write `inventory`, never `products`.

The map is filled once at load: `INSERT INTO product_merchant_map SELECT product_id,
merchant_id FROM products` (`expt_b10/run.sh` lines 575-580, which carry the same comment). It
holds 500,000 rows, distributed by `product_id` (`colocate_with => 'none'`, line 540).

**Effect** (`tx_by_clients.csv`, `step_prediction.csv`):

- T7: 32.7 -> 4.4 ms at 1 client, 884.8 -> 9.0 ms at 64.
- T7 now does 4 single-shard tasks (2 lookups, debit, credit) instead of 192, and none takes
  the shard lock.
- Mean TPS 1.59x, 1.56x at 64 clients.
- **T7's speed-up alone would predict 23.5x at 64 clients** (closed-loop model below). TPS
  rose only 1.56x because T5, unchanged, took over the queue (Beat 1 table, b10 row).

**Closed-loop model used throughout** (`closed_loop_check.csv`). pgbench has no think time, so
TPS = N / R, where R = sum over transactions of weight x mean latency.

- X x R / N is within 0.4% of 1 for b13-b20 at every client count.
- Earlier gaps have known causes: aborted clients (b8 at 8 clients gives 7.14, with one of its 8 clients
  aborted) and multi-second transactions cut off at the end of the run (b0, b7).
- With this model, the change in TPS between two runs splits exactly into per-transaction
  pieces, weight x change in latency (`response_time_delta.csv`).
- "pred_t7_only" asks what TPS would be if only T7's latency had changed.

## Beat 3: convergence with A (b11-b15), briefly

**Figure B, `fig:b-clients-inside`** (`clients_inside_c64.csv`) shows the whole sequence in
one chart: where the 64 clients are, by Little's law. It can replace or sit beside
`tab:b-bottleneck`.

| B step | A analogue (as cited in the current LaTeX, not checked against the A folders) | Mean TPS vs parent | Largest share after, at 64 clients |
| --- | --- | ---: | --- |
| b11: T5 via `order_merchant_map` | a4 | 1.07x | T6, 42.1 clients |
| b12: T6 from the daily rollup | a5 | 3.01x | T6 26.8, T1 16.2 |
| b13: T1 delegated | a7 | 1.11x | T6, 32.3 |
| b14: 8 shards | a10 | 1.87x | T6, 26.4 |
| b15: 4 shards | (none cited) | 1.20x | T7, 29.1 (45.6% of latency) |

Earlier steps cross-cite a1 (b7), a2 (b8), a3 (b9) and a8 (b10).

## Beat 4: B-specific work on T7 (b16-b19), then b20

**Why bother with a 4.6 ms transaction.**

- In b15, T7 is still 36.2% of latency at 1 client and **45.6% at 64**, holding 29.1 clients.
- Even a free T7 would give at most 1 / (1 - 0.456) = 1.84x at 64 clients.
- b15 is already near saturation there: TPS rises only 2.8% from 32 to 64 clients (3,792.3 ->
  3,897.1).

**What each variant does per T7 call** (from the transaction SQL and `t7_plans.csv`):

| Variant | Statements from the client | Worker tasks | Where the lookup runs | Commit across workers |
| --- | --- | --- | --- | --- |
| b8/b9 (no map) | 6 + `BEGIN`/`COMMIT` | 192 (6 x 32 shards) | - | always, all 4 workers |
| b10-b15 sharded map | 4 + `BEGIN`/`COMMIT` | 4 | worker holding the map shard | 75% of calls |
| b16 delegated | 2 lookups + 1 call | 3, plus a new worker-to-worker connection for a remote credit | worker | 75%, coordinated by the worker |
| b17 reference table | 4 + `BEGIN`/`COMMIT` | 2 (+2 on the coordinator's replica) | coordinator | 75% |
| b18 merged lookup | 3 + `BEGIN`/`COMMIT` | 4 (the lookup is 2 parallel tasks) | workers | 75% |
| b19/b20 both | 3 + `BEGIN`/`COMMIT` | 2 (+1 on the coordinator) | coordinator | 75% |

**Figure D, `fig:b-t7-variants`** (`t7_latency.csv`, `rel_tps.csv`) should replace `fig:b-t7`,
since it covers all six client counts. Error bars are within-run 95% intervals from ten 60 s
windows.

| | b15 | b16 | b17 | b18 | b19 | b20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| T7 mean, 1 client (ms) | 4.59 | 8.09 | 2.96 | 4.06 | 3.68 | 3.56 |
| T7 mean, 64 clients (ms) | 24.93 | 42.28 | 26.43 | 22.18 | 19.84 | 19.69 |
| TPS vs b15, 1 client | 1 | 0.794 | 1.222 | 1.029 | 1.062 | 1.118 |
| TPS vs b15, 4 clients | 1 | 0.844 | 1.115 | 1.049 | 1.102 | 1.182 |
| TPS vs b15, 64 clients | 1 | 0.686 | 0.980 | 1.006 | 1.032 | 1.052 |

**Figure E, `fig:b-b16-hist`** (`t7_hist_c1.csv`): direct evidence for the b16 explanation (new).

- At 1 client, b16's T7 is **bimodal**: one mode at about 1.5-3.5 ms, the other at about
  7.5-11.5 ms, and no call in between.
- The fast mode holds **24.96%** of 37,513 calls (25.05% of 180,536 at 4 clients).
- The same-worker probability from the placement is **25.03%**.
- So the fast calls are the ones whose credit is local. A remote credit costs about 7 ms
  extra, the price of the new connection the worker backend opens on every call (the Citus
  `ShouldShutdownConnection` citation already in the LaTeX).
- b15's distribution is unimodal (98% under 5.5 ms).

**Figure F, `fig:b-absorption`** (`response_time_delta.csv`, `step_prediction.csv`): the gap
between T7's cut and the TPS gain. Units are ms of mean response time per transaction; b15's R
at 64 clients is 16.4 ms.

| 64 clients | T7 | T1 | T6 | others | net | TPS from T7 alone | TPS measured |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| b17 | +0.45 | -0.45 | -0.26 | +0.59 | +0.34 | -2.7% | -2.0% |
| b18 | -0.83 | +0.42 | +0.35 | -0.05 | -0.10 | +5.3% | +0.6% |
| b19 | -1.53 | +0.59 | +0.39 | +0.02 | -0.53 | +10.3% | +3.2% |

- At 1 client, T7's change carries straight through: b19 predicts +7.7% from T7 alone and
  measures +6.2%.
- At 64 clients, T1 and T6 give back two-thirds of what T7 saves. The system is saturated, so
  freed clients queue in the next transaction.
- This is the same "fixing one exposes the next" pattern as Beats 1-2, on a small scale. It
  also explains why TPS changes of a few percent are all T7 work can buy at 64 clients.

**b17 caveats.**

1. Its conditions check fails: the untouched T2/T4/T8/T9 are 21% faster at 1 client
   (`../control_check_c1.csv`, geometric mean 0.792). So the +22% at 1 client is mostly run
   conditions.
2. Its within-run noise is also larger at 8 clients (95% CI +-4.5%).
3. A plan observation, single cold execution, not conclusive: the reference-table lookup's task
   runs on `xcnf17`. It takes **4.3-5.1 ms** of coordinator time in b17, b19 and b20, against
   1.3-1.7 ms for the sharded lookup in b12-b16, with 0.05-0.08 ms of actual work.
   `citus.log_local_commands = on` (b19, b20) printed no "executing the command locally"
   notice. It may be first-use connection setup. It does not explain the steady-state numbers
   (T7 is faster in b17 at 1 client), so cite it, if at all, only as a lead for the 64-client
   loss.

**b20 (REPEATABLE READ): where its small gain comes from (new).** T6, the transaction with the
largest read set, accounts for most of it (`tx_by_clients.csv`):

- At 1 client, every transaction is about 3% faster than in b19, matching the conditions check
  (0.969). T6 alone is **11.9%** faster (8.61 -> 7.59 ms).
- At 64 clients, T6 is 5.8% faster against 0.3-2.0% for the others. T6 supplies -0.18 of the
  -0.30 ms net change in response time.

This fits the read tracking (SIREAD locks) that only `SERIALIZABLE` performs. That is a
hypothesis consistent with the data, not something measured directly. Retried transactions and
serialization failures did not fall (below).

## Retries (corrected numbers)

`summary.csv` has two columns, and the LaTeX quotes the first as "retries":

| 64 clients | b12 | b13 | b15 | b19 | b20 |
| --- | ---: | ---: | ---: | ---: | ---: |
| retried transactions | 3,371 | 2,027 | 5,996 | 7,649 | 7,924 |
| total retries | 3,745 | 2,203 | 6,569 | 8,581 | 8,889 |
| serialization failures | 127 | 19 | 83 | 141 | 181 |

By transaction (`retries_by_tx.csv`), T1 accounts for nearly all of them: 1.9-3.9% of T1s are
retried at 64 clients from b12 on (b19: 3.06%, b20: 3.11%). From b13 on, no other transaction
exceeds 0.03%; in b11 and b12, T6 is also retried (1.5% and 1.1%).

## Noise and stability

- **Within-run noise** (`noise_batch_means.csv`): 95% CI half-width 0.5-1.5% of TPS for
  b15-b20 at most client counts (b17 at 8 clients 4.5%, b20 at 16 clients 2.9%). It is 1-3% for
  b8, b9 and b12, up to 6-10% at some client counts for b10, b11, b13 and b14, and 7-16% for b0
  and b7.
- It says nothing about run-to-run variation. That is about +-5% from the conditions check, so
  use +-5% as the floor in the text and the CIs only as error bars.
- **Time series** (`tps_timeseries_10s.csv`, 10 s windows): at 64 clients, b15-b20 vary by
  1.4-2.6% (coefficient of variation), except b19 at 5.0%.
- That is because b19 has one 10 s window at 2,598 TPS (180-190 s). Without it, its 64-client mean would be
  4,044.8 instead of 4,020.7 (+0.6%).
- b12-b14 vary by 5-9%, and b10/b11 by 11-14%.

## Corrections for the current LaTeX draft

1. **Retries.** "retries reach 3,371" (b12), "2,027" (b13), "7,649" (b19) and "7,924" (b20) are
   retried transactions. Either say "transactions retried" or use the total-retries row above.
2. **b20 correctness paragraph: the T4 sentence is false.**
   - T1 does write `inventory` (`place_order` step 3) and reads `products.price` (step 2).
   - T4 reads `products.price` and `inventory.quantity` of one product in one statement, and
     T9 writes `price`.
   - Under snapshot isolation: T1 reads P's old price, T9 updates P's price and commits, then
     T4 starts and reads P's new price with the stock T1 has not yet committed.
   - This forms the cycle T1 ->rw T9 ->wr T4 ->rw T1, the read-only anomaly, which
     `SERIALIZABLE` would abort. It needs all three on the same product at once, so it is rare,
     but "every execution under REPEATABLE READ is one SERIALIZABLE would also allow" does not
     hold. The comment above the paragraph already flags this assumption.
   - Either narrow the claim (no lost updates, `CHECK`s hold, the only new anomaly is this T4
     read) or drop the proof.
3. **b10 "which suggests that concurrent T5s execute one after another"** can now be stated as a
   fact, with the Citus lock citation above.
   - The ceiling arithmetic (36.3 / 0.10 = 363) is an identity: with a fixed mix, X_i / w_i
     equals total TPS for every transaction.
   - What makes T5 the limit is that its own rate stays flat while its latency grows. Same for
     T6 in b11 (39.5 / 0.10).
4. **"three times in four"** -> 74.9% (32 shards) / 75.0% (4 shards), computed (`placement.csv`).
5. **b16**: add the bimodal histogram as evidence (Figure E). Note also that
   `expt_b16/optimisations.md` says the worker "opens and caches" the connection; the source and
   the histogram both say it does not cache it.
6. **Alternative partitioning comment.** If `inventory` were distributed by `product_id`:
   - T1 would lose colocation: `place_order` joins `inventory` with `products` and writes
     `inventory`, `orders` and `order_items` in one transaction, so it could no longer be
     delegated whole.
   - T2 would not: it has both `product_id` and `merchant_id`, so it stays single-shard.
7. **b7 paragraph**: the T1/T5 shared queue (12.5 s each at 64 clients) and T5's 1-client
   slowdown are both missing; see Beat 1.

## Files

| File | Feeds | Contents |
| --- | --- | --- |
| `latency_by_tx.csv` | Fig. A | mean latency per transaction, 1 and 64 clients, every experiment |
| `clients_inside_c64.csv` | Fig. B | Little's-law clients per transaction at 64 clients |
| `latency_share.csv` | (table) | share of latency per transaction, 1 and 64 clients |
| `tx_by_clients.csv` | Fig. C | every transaction: mean latency and own TPS at every client count |
| `t7_latency.csv` | Fig. D (left) | T7 mean/p50/p95/p99, share, clients inside |
| `rel_tps.csv` | Fig. D (right) | TPS ratio to b15 (also b20/b19, b10/b9, b8/b7) with within-run CI |
| `t7_hist_c1.csv` | Fig. E | T7 latency histogram at 1 client, 0.25 ms bins, b15-b19 |
| `t7_cdf.csv` | (optional) | T7 percentiles 0.5-99.9 at 1 and 64 clients, every experiment |
| `response_time_delta.csv` | Fig. F | per step and client count: weight x change in latency, per transaction |
| `step_prediction.csv` | Fig. F | measured TPS ratio vs closed-loop predictions (all transactions / T7 only) |
| `closed_loop_check.csv` | (method) | X x R against N |
| `noise_batch_means.csv` | (caveats) | TPS from the logs (equals `summary.csv` exactly), 60 s batch mean/sd/CI |
| `tps_timeseries_10s.csv` | (optional) | TPS per 10 s window, every run |
| `retries_by_tx.csv` | (retries) | successful, failed, retried transactions and retries per transaction |
| `t7_plans.csv` | (T7 table) | T7 statements in `explain.log` (b12 on): tasks, node, coordinator/worker time |
| `placement.csv` | (Beat 1) | merchants and hot merchants per worker, P(T7 crosses workers), per shard count |
