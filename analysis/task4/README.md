# Task 4 data pack: optimising workload B (expt_b7 .. expt_b20)

> **Superseded by [`pack/README.md`](pack/README.md)** (2026-10-13), the evidence pack for Section 5,
> which covers every run up to `expt_b46`. Kept for the analyses it describes in more detail.

> **Renumbered 2026-10-11.** The `REPEATABLE READ` run described here as `expt_b20` is now
> `expt_b26` (not carried forward); `expt_b19` is the final design. `expt_b20`/`expt_b21` are
> new replicates of `expt_b19` and `expt_b22`..`expt_b25` the partitioning cells. The CSVs
> use the new names; the prose below still uses the old ones.

> For the rewritten narrative (A's design first, then the product map, then T7-specific work),
> figure data, ready pgfplots figures and corrections to the LaTeX draft, see
> [`narrative/README.md`](narrative/README.md).

Source material for Section 5 of the report. Every number below comes from
the CSVs in this folder, which `collect.py` builds from each experiment's
`slurm-results/` (re-run it with `python3 analysis/task4/collect.py`). Nothing
is estimated. The per-experiment design notes are in each
`expt_bN/optimisations.md`; this file says where to look and what the data
shows.

| File | Contents |
| ---- | -------- |
| `chain_overview.csv` | per experiment: TPS at each client count, mean and peak TPS, ratios to parent and to `expt_b0`, invalid client counts |
| `chain_summary.csv` | per experiment x client count: TPS, p50/p95/p99 latency, retries, serialization and deadlock failures, exit code, aborted clients and their error, validity |
| `chain_transactions.csv` | per experiment x client count x transaction: TPS, avg/p50/p95/p99 latency, share of total latency, clients inside the transaction (Little's law) |
| `chain_bottleneck.csv` | per experiment x client count: the transaction with the largest latency share |
| `control_check_c1.csv` | conditions check: latency of the unchanged T2/T4/T8/T9 at 1 client against the parent |

Definitions used throughout:

- **TPS** is `overall_tps` from `summary.csv` (successful transactions over the
  600 s measured run). **Mean TPS** is the mean over the six client counts
  (1, 4, 8, 16, 32, 64). The brief's metric is "average transaction
  throughput"; mean TPS, TPS at 64 clients and peak TPS are all given, so the
  report can pick one and say which.
- **Share of latency** = `successful_transactions x avg_latency_ms` of a
  transaction over the sum for all nine (the definition every
  `optimisations.md` uses).
- **Clients inside** a transaction = its TPS x its average latency in seconds
  (Little's law); at 64 clients the nine values sum to about 64.
- **Valid** follows `analysis/plot_results.py` on `main`: a point is not valid
  when `pgbench_exit_code != 0` or at least one client aborted.

## 1. Numbering and run conditions

The report skeleton still uses the old names. The folders were renumbered:
old `bN` is now `b(N+6)`; `b1`..`b6` now hold the baseline parameter study
(Task 3), and old `b15` (READ COMMITTED) no longer exists.

| Skeleton | Folder | Parent | Change | Job | Run start |
| -------- | ------ | ------ | ------ | --- | --------- |
| - | `expt_b0` | - | baseline (for the overview only) | 916257 | 2026-10-07 01:25 |
| b1 | `expt_b7` | b0 | colocate all tenant tables by `merchant_id`, query-matched indexes, fill factors, no `BEGIN`/`COMMIT` around single statements | 920777 | 2026-10-08 14:14 |
| b2 | `expt_b8` | b7 | `merchant_id` in T3's join, `IS DISTINCT FROM` guards on T5/T8, `merchant_id` in T1's final `UPDATE` | 920778 | 2026-10-08 15:29 |
| b3 | `expt_b9` | b8 | set-based T1 (one CTE statement) | 920779 | 2026-10-08 16:41 |
| b4 | `expt_b10` | b9 | T7 routed via `product_merchant_map` (sharded by `product_id`) | 920780 | 2026-10-08 17:54 |
| b5 | `expt_b11` | b10 | T5 routed via `order_merchant_map`, written by T1 | 920781 | 2026-10-08 19:06 |
| b6 | `expt_b12` | b11 | T6 from the `merchant_daily_sales` rollup, upserted by T1 | 880152 | 2026-09-25 17:10 |
| b7 | `expt_b13` | b12 | T1 as the delegated function `place_order` | 881165 | 2026-09-25 23:34 |
| b8 | `expt_b14` | b13 | 8 shards instead of 32 | 882974 | 2026-09-26 19:47 |
| b9 | `expt_b15` | b14 | 4 shards, one per worker | 883179 | 2026-09-26 21:31 |
| b10 | `expt_b16` | b15 | T7 as a delegated function (not carried forward) | 884062 | 2026-09-27 10:36 |
| b11 | `expt_b17` | b15 | `product_merchant_map` as a reference table on the coordinator | 885153 | 2026-09-27 23:28 |
| b12 | `expt_b18` | b15 | T7's two lookups merged into one statement | 886108 | 2026-09-28 13:17 |
| b13 | `expt_b19` | b15 | reference table and merged lookup combined | 886110 | 2026-09-28 14:31 |
| b14 | `expt_b20` | b19 | `REPEATABLE READ` instead of `SERIALIZABLE` (final design) | 887306 | 2026-09-28 21:05 |

Every run above used `xcnf[17-21]` (1 coordinator, 4 workers) and ran with no
other benchmark job on those nodes (checked from the start/end times of every
B-side job, including the deleted ablation grid, which ran 2026-10-07 09:59 ..
2026-10-08 05:36 and 2026-10-09 00:15 .. 03:55). `expt_b7`..`expt_b11` are
reruns from 2026-10-08 (the originals ran on `xcnf[16-20]` and were deleted);
they did not record plans, so `explain.log` exists only from `expt_b12` on.
The `optimisations.md` cross-references already use the new numbers.

## 2. Headline numbers (overview paragraph)

| | `expt_b0` | `expt_b20` | Ratio |
| - | --------- | ---------- | ----- |
| Mean TPS (6 client counts) | 7.05 | 2,710.0 | 384x |
| TPS at 1 client | 6.68 | 294.2 | 44x |
| TPS at 64 clients | 6.38 | 4,098.5 | 642x |
| Peak TPS | 7.81 (16 clients) | 4,098.5 (64 clients) | 525x |
| p99 latency at 64 clients | 97,018 ms | 72.9 ms | |

`expt_b0` is not valid at 8, 16 and 32 clients (1, 5 and 4 clients aborted on
`could not commit transaction`); its mean includes those points.

Mean TPS along the main chain (ratio to parent in brackets):
b0 7.05, b7 10.99 (1.56x), b8 199.8 (18.2x), b9 198.1 (0.99x),
b10 315.9 (1.59x), b11 337.0 (1.07x), b12 1,014.1 (3.01x), b13 1,124.5
(1.11x), b14 2,103.1 (1.87x), b15 2,528.1 (1.20x), b19 2,657.6 (1.05x vs
b15), b20 2,710.0 (1.02x). Side branches from b15: b16 1,796.9 (0.71x),
b17 2,504.2 (0.99x), b18 2,567.6 (1.02x).

### Throughput at every client count

`overall_tps` from each `summary.csv` (the same numbers are the `tps_c<N>`
columns of `chain_overview.csv`). `*` marks a point that is not valid
(non-zero `pgbench_exit_code` or an aborted client; see section 6). Mean is
over the six client counts; Peak is the highest TPS and the client count it
was reached at.

| Experiment | Skeleton | c1 | c4 | c8 | c16 | c32 | c64 | Mean | Peak (clients) |
| ---------- | -------- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `expt_b0` | - | 6.7 | 7.5 | 7.7* | 7.8* | 6.3* | 6.4 | 7.1 | 7.8 (16) |
| `expt_b7` | b1 | 9.2 | 11.4 | 11.0 | 12.5 | 10.4 | 11.3 | 11.0 | 12.5 (16) |
| `expt_b8` | b2 | 61.6 | 215.7 | 229.5* | 223.7 | 231.2* | 237.1* | 199.8 | 237.1 (64) |
| `expt_b9` | b3 | 58.4 | 213.9 | 228.6 | 225.0 | 229.5 | 233.2 | 198.1 | 233.2 (64) |
| `expt_b10` | b4 | 116.4 | 331.8 | 363.5 | 355.4* | 363.5* | 364.5* | 315.8 | 364.5 (64) |
| `expt_b11` | b5 | 122.9 | 354.7 | 385.9 | 375.1 | 384.3 | 398.9* | 337.0 | 398.9 (64) |
| `expt_b12` | b6 | 165.8 | 809.7 | 1,519.7 | 1,223.9 | 1,267.0 | 1,098.7* | 1,014.1 | 1,519.7 (8) |
| `expt_b13` | b7 | 206.9 | 1,040.5 | 1,548.0 | 1,232.0 | 1,482.1 | 1,237.6 | 1,124.5 | 1,548.0 (8) |
| `expt_b14` | b8 | 250.2 | 1,127.0 | 2,507.9 | 3,188.6 | 3,110.7 | 2,434.3 | 2,103.1 | 3,188.6 (16) |
| `expt_b15` | b9 | 263.1 | 1,187.7 | 2,642.1 | 3,386.2 | 3,792.3 | 3,897.1 | 2,528.1 | 3,897.1 (64) |
| `expt_b16` | b10 | 208.9 | 1,003.1 | 1,864.3 | 2,398.7 | 2,633.8 | 2,672.9 | 1,796.9 | 2,672.9 (64) |
| `expt_b17` | b11 | 321.4 | 1,324.8 | 2,432.6 | 3,349.9 | 3,776.4 | 3,820.1 | 2,504.2 | 3,820.1 (64) |
| `expt_b18` | b12 | 270.9 | 1,245.9 | 2,699.8 | 3,430.6 | 3,838.0 | 3,920.0 | 2,567.5 | 3,920.0 (64) |
| `expt_b19` | b13 | 279.5 | 1,309.5 | 2,803.7 | 3,573.1 | 3,958.7 | 4,020.7 | 2,657.5 | 4,020.7 (64) |
| `expt_b20` | b14 | 294.2 | 1,403.8 | 2,930.2 | 3,537.9 | 3,995.6 | 4,098.5 | 2,710.0 | 4,098.5 (64) |

## 3. Per-experiment facts

Latencies are per-transaction averages from `chain_transactions.csv`.

**`expt_b7`: colocation by `merchant_id` (skeleton b1).**
Mean TPS 7.05 -> 10.99 (1.56x); 1 client 6.68 -> 9.23. T4 falls from 362 ms
to 1.0 ms at 1 client (now one shard), but T3 is unchanged (1,945 -> 1,873
ms) because its join still lacks `merchant_id`, and T3 is 86% of latency at 1
client. T7 barely moves (36.2 -> 30.3 ms): it transfers stock between two
products drawn uniformly from all 500,000, so the two rows usually belong to
different merchants and, with 4 workers, sit on different workers 3 times in
4. Colocating by merchant cannot help a transaction that is not
merchant-scoped (`expt_b7/optimisations.md`, "Caveat: T7"). No serialization
failures at any client count (b0 had 870 at 64). All points valid.

**`expt_b8`: distribution-column predicates (b2).**
T3 1,873 -> 1.4 ms at 1 client; mean TPS 18.2x (10.99 -> 199.8), 237.1 at 64
clients (21x b7). T7 is now 60% of latency at 1 client and 97% at 64, with
61 of the 64 clients inside it. Not valid at 8, 32, 64 clients (1-2 clients
aborted on `could not commit transaction`, T1).

**`expt_b9`: set-based T1 (b3).** A surprising result: T1 got slower at 1
client, 10.3 -> 19.2 ms, despite replacing about 18 coordinator round trips
with one statement. No plan was recorded for b9, but `expt_b12`'s
`explain.log` (the same CTE plus the map insert and rollup upsert) shows the
statement executed as 10 separate single-task subplans, each a round trip
through the coordinator. Throughput unchanged (0.99x), since T7 still holds 62 of 64
clients. All points valid.

**`expt_b10`: T7 routing via `product_merchant_map` (b4).**
T7 32.7 -> 4.4 ms at 1 client, 885 -> 9.0 ms at 64; mean TPS 1.59x
(364.5 at 64). The bottleneck jumps to T5, whose code did not change: 9.7 ms at
64 clients in b9, 1,561.7 ms in b10 (162x slower). T5's own TPS is flat at
about 36 from 8 clients on, 57 of 64 clients are inside it, and
36.3 / 0.10 = 363 TPS is the observed ceiling. In b9, T7 held 62 of 64
clients, so T5 never ran concurrently. Not valid at 16, 32, 64 (1 client
aborted each, T7, `could not commit transaction`).

**`expt_b11`: T5 routing via `order_merchant_map` (b5).**
T5 1,562 -> 28.6 ms at 64 clients, but mean TPS only 1.07x (398.9 at 64):
T6 now caps it, 66% of latency and 42 of 64 clients at 64; T6 at 1,067 ms.
39.5 / 0.10 = 395 TPS is the ceiling. T1 rises to 214.5 ms at 64 clients
(34.1 in b10): every T1 now also inserts a map row on another worker and
commits in two phases. Not valid at 64 (1 client aborted, T7).

**`expt_b12`: T6 from the rollup (b6).**
T6 1,067 -> 245 ms at 64 clients, 43.2 -> 18.7 ms at 1; mean TPS 3.01x
(1,014.1). The throughput curve changes shape: peak 1,519.7 at 8 clients,
then down to 1,098.7 at 64. Serialization failures appear (14/63/127 at
16/32/64) and retries jump (3,371 at 64): T1 now upserts one rollup row per
merchant per day, and the 100 hot merchants receive 50% of orders. T6 still
runs as 32 shard tasks (`explain.log`: `Task Count: 32`). The exactness
argument (rollup + boundary day = the baseline's answer) is in
`expt_b12/optimisations.md`. Not valid at 64 (1 client aborted, T7).

**`expt_b13`: delegated T1 (b7).**
T1 21.7 -> 10.1 ms at 1 client; `explain.log` shows the call as one task
whose query is `SELECT public.place_order(...)`, against b12's 10 single-task
subplans. Mean TPS 1.11x (1,124.5; peak 1,548 at 8, 1,237.6 at 64). Retries at
64 clients fall 3,371 -> 2,027 and serialization failures 127 -> 19 (the
rollup row is held for one round trip instead of many). T6 is now the
largest share at 64 clients (50.5%). All points valid.

**`expt_b14`: 8 shards instead of 32 (b8).**
T6 263 -> 108.5 ms at 64 clients, 18.8 -> 10.0 ms at 1; mean TPS 1.87x
(2,103.1), peak 3,188.6 at 16, 2,434.3 at 64. `explain.log`: T6 `Task Count`
32 -> 8, coordinator execution 31.1 -> 20.1 ms while the sampled task's own
execution rises 2.6 -> 3.6 ms: the cost was per-task overhead, not data. The
failed alternative (per-merchant running totals for T6, motivated by a
pre-`VACUUM` plan that made the rollup scan look 4x more expensive than it is)
is written up in `expt_b14/optimisations.md`, "An idea that did not work",
with local docker measurements. All points valid.

**`expt_b15`: 4 shards (b9).**
T6 108.5 -> 28.1 ms at 64 clients; mean TPS 1.20x, TPS at 64 1.60x
(3,897.1). The curve no longer peaks and falls: TPS rises at every client
count (b12-b14 all peaked at 8-16 and declined). T6 `Task Count: 4`,
coordinator 15.1 ms. T7 becomes the largest share (45.6% at 64 clients,
29 clients inside). All points valid.

**`expt_b16`: T7 as a delegated function (b10, not carried forward).**
Worse: mean TPS 0.71x, 2,672.9 at 64 (b15 3,897.1). T7 4.6 -> 8.1 ms at 1
client, 24.9 -> 42.3 ms at 64. Mechanism: the delegated call runs in a worker
backend that serves an internal Citus connection, and Citus never caches
outgoing connections from such backends (`ShouldShutdownConnection` returns
true for `IsCitusInternalBackend()`, Citus v14.1.0
`src/backend/distributed/connection/connection_management.c` lines
1533-1552). So the credit on another worker (3 transfers in 4) opens a new
connection every call. Note: `expt_b16/optimisations.md` says the worker
"opens and caches" that connection; the source shows it is not cached. All
points valid.

**`expt_b17`: reference table (b11).**
T7 4.6 -> 3.0 ms at 1 client; TPS +22% at 1 client but -2% at 64 (mean
0.99x). Caution: the conditions check fails for this run. T2, T4, T8 and T9,
which the change does not touch, are 21% faster at 1 client than in b15
(`control_check_c1.csv`, geometric mean 0.79; every other run is within
+-5% of its parent). Most of the 1-client gain is therefore the run's
conditions, not the reference table. The README's "coordinator CPU"
explanation for the high-client loss is a hypothesis; no CPU was measured.

**`expt_b18`: merged lookup (b12).**
T7 9-13% faster at every client count; TPS +3% at 1 client, +0.6% at 64
(mean 1.02x). `expt_b18/optimisations.md` has a full results table
(job-886108). Controls within 1.4% of b15.

**`expt_b19`: reference table + merged lookup (b13).**
Mean TPS 1.05x b15, TPS 279.5 at 1 client (+6%) and 4,020.7 at 64 (+3%); T7
24.9 -> 19.8 ms at 64. Controls 3.6% slower than b15, so the gain is not a
conditions artefact. Together with b17 and b18 this is an interaction
worth reporting: reference table alone 0.99x, merged lookup alone 1.02x,
both 1.05x (mean TPS).

**`expt_b20`: REPEATABLE READ (b14, final design).**
Mean TPS 1.02x, 294.2 at 1 client (+5%), 4,098.5 at 64 (+2%); the best at 64
clients. Retries and serialization failures did not fall (7,924 and 181 at 64,
against 7,649 and 141). Controls are 3% faster than b19, so most of the gain is
within the noise floor (section 6). The correctness argument (only write skew
is newly allowed, and no transaction can produce it) is in
`expt_b20/optimisations.md`, "Why the transactions still behave like
expt_b0". Its motivation comes from b19's worker logs over the whole job:
18,140 write-write conflicts (`could not serialize access due to concurrent
update`) against 488 SSI read/write-dependency errors, so `REPEATABLE READ`
can remove at most 2.6% of the conflicts; 17,216 (95%) of the write-write
conflicts are T1's upsert of the hot merchant's rollup row for today, and
3.1% of T1s were retried at 64 clients against at most 0.03% of any other
transaction. These pre-run notes predict exactly the outcome measured: a
small gain, with the rollup-row conflicts still present.

## 4. Cross-cutting analyses

**Bottleneck progression at 64 clients** (`chain_bottleneck.csv`,
`chain_transactions.csv`). Each fix moves the queue to the next transaction:

| Experiment | Largest share at 64 clients | Share | Clients inside |
| ---------- | --------------------------- | ----- | -------------- |
| b0 | T3 Order History | 62.4% | 35.8 |
| b7 | T3 | 40.7% | 26.7 |
| b8, b9 | T7 Inventory Transfer | 97% | 61-62 |
| b10 | T5 Update Order Status | 88.8% | 56.7 |
| b11 | T6 Global Sales | 66.0% | 42.1 |
| b12-b14 | T6 | 41-51% | 26-32 |
| b15-b20 | T7 | 38-53% | 24-34 |

From b15 on, no transaction holds more than about half the clients; T1 and
T6 hold 12-15 each. A stacked latency-share chart per experiment at 64
clients shows this best (`plot_results.py` on `main` draws
`latency_share_c64`).

**Curve shape and shard count.** With 32 shards (b12, b13) and 8 (b14),
throughput peaks at 8-16 clients and falls by 20-28% by 64. With 4 shards
(b15 on) it rises monotonically to 64. T6's latency at 64 clients:
245 / 263 / 108.5 / 28.1 ms for b12 / b13 / b14 / b15.

**Retries come with the rollup.** Serialization failures are zero from b7 to
b10 and start at b11-b12, when T1 starts writing the map and the rollup.
Retries grow with throughput (b15 5,996 -> b19 7,649 -> b20 7,924 at 64) and
are almost all T1 (`expt_b19`/`expt_b20` notes). No deadlocks in any run.

**Plans** (`explain.log`, b12-b20 only): T6 tasks 32 (b12, b13) -> 8 (b14) ->
4 (b15-b20); T1 one delegated task from b13; T7 single-task routed
statements, with b18's merged lookup one statement of `Task Count: 2`.

## 5. Candidate "interesting" and "surprising" results

Ranked by strength of evidence:

1. **Fixing one bottleneck exposes the next, sometimes in unchanged code.** T5
   ran 9.7 ms in b9 and 1,562 ms in b10 without being modified (section 3,
   b10). The latency-share table in section 4 shows the full sequence.
2. **Delegating T1 helped; delegating T7 hurt** (b13 vs b16), for a reason
   visible in Citus's source: a delegated function that writes to another
   worker opens a new connection every call. T1 writes remotely only for the
   map row; T7's credit is remote 3 times in 4.
3. **Fewer shards turned a peaking curve into a rising one** (b12-b14 vs
   b15), with plan evidence that T6's cost was per-task overhead.
4. **Set-based T1 was slower than 18 round trips** (b9), and the
   running-totals idea for T6 that was dropped before it ran (b14 notes).
   Both are "the obvious optimisation did not help" results.
5. **Reference table and merged lookup only helped together** (b17 0.99x, b18
   1.02x, b19 1.05x mean TPS), but the effects are small and b17 ran under
   different conditions; present with the noise caveat.
6. **REPEATABLE READ barely helped and did not reduce retries** (b20), as its
   pre-run notes predicted: the retries are write-write conflicts on T1's
   hot rollup row, which snapshot isolation still detects.

## 6. Validity, noise and caveats

- **Invalid points** (`chain_summary.csv`, `valid = False`): b0 at 8/16/32,
  b8 at 8/32/64, b10 at 16/32/64, b11 at 64, b12 at 64. Every one is 1-5
  aborted clients on `could not commit transaction`, an error at commit that
  pgbench does not retry. b13-b20 are valid everywhere. Plots should mark
  these points (`plot_results.py` draws them hollow).
- **Noise floor.** No chain run has a replicate yet. The conditions check
  puts run-to-run conditions within about +-5% at 1 client (b17 excepted at
  -21%), so differences of a few percent (b18, b19, b20 against their
  parents) are at the noise level. `expt_b21` and `expt_b22` (replicates of
  b20, see `ablation_b20/`) will measure it; until then, say so.
- **Stale notes.** `expt_b16`, `b17`, `b19` and `b20`'s `optimisations.md`
  end with "this experiment has not been run yet"; they were written before
  the runs and contain predictions, not results (except b18, which has a
  results section). b16's "opens and caches a connection" is wrong (section
  3, b16).
- **b0 is valid at 1, 4 and 64 clients only**, so any b0 ratio at 8-32
  clients compares against a run with aborted clients.

## 7. Alternative partitioning (skeleton subsection)

No experiment in any branch changed the distribution column away from
`merchant_id`. What exists:

- **Routing alternatives for T7 within merchant distribution**: `expt_b10`
  (sharded lookup map), `expt_b16` (delegated function, worse),
  `expt_b17`/`expt_b19` (reference-table map), `expt_b18` (merged lookup).
- **A discarded formula-routed T7** (commit `73643b46`, job 860455,
  `xcnf[17-21]`, 2026-09-18): it computed each product's merchant as
  `1 + (product_id - 1) % NUM_MERCHANTS`, which only holds for this data
  generator, so it was dropped for the lookup map. 131.8 TPS at 1 client and
  360.2 at 64, but not valid at 4-64 clients and run in an earlier period, so
  it is context, not comparable evidence.
- **The case for `merchant_id` in the data**: T4 362 -> 1.0 ms and T3 2 s ->
  1.4 ms once merchant-scoped transactions reach one worker (b7, b8); T1 can be
  delegated whole (b13) only because a merchant's customers, products,
  inventory and orders are colocated. T7 is the one transaction that loses,
  and routing (b10) cut it from 885 to 9.0 ms at 64 clients without changing
  the distribution.

Direct evidence is set up but not yet run: `partitioning_b20/` builds four
what-if placements from `expt_b20`, each removing one cost of `merchant_id`
(see its README for every change and what to compare against):

| Cell | Placement | Removes | Costs |
| ---- | --------- | ------- | ----- |
| `expt_b38` | `products` + `inventory` by `product_id` | T7's lookup | T1 spans workers and is not delegated |
| `expt_b39` | `orders` + `order_items` by `order_id` | T5's lookup and `order_merchant_map` | T3 asks every shard |
| `expt_b40` | `products` + `inventory` on one node (single-shard tables) | T7's lookup and cross-worker commit | every catalog access on one worker |
| `expt_b41` | `inventory` as a reference table | T7's lookup | every inventory write to all 5 nodes |

b38, b40 and b41 use the original (non-delegated) T1, the same as the
ablation's `expt_b26`, so `expt_b26` isolates the placement from the T1
change; b39's T1 is the ablation's `expt_b23`'s.

## 8. Pending

The ablation around `expt_b20` (`ablation_b20/README.md`: replicates
`expt_b21`, `expt_b22` and the 2^4 factorial `expt_b23`..`expt_b37` over T5
routing, T6 rollup, T7 routing and T1 delegation, run one at a time) has not
run yet. When it has, it gives the noise floor (section 6) and every
optimisation's leave-one-out contribution in the final design, which the
brief names as the alternative to the progressive chain. The what-if
placements `expt_b38`..`expt_b41` (section 7) have not run either.
