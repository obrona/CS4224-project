# Task 4 evidence pack: optimising workload B

Source material for Section 5 (Task 4: optimised design for workload B). It
supersedes `../README.md` and `../narrative/README.md`, whose numbers it reuses
where they are still current. Every number here comes from the runs, through
`collect_pack.py` (this folder's CSVs) and the earlier scripts listed in
section 9. Regenerate with:

```sh
python3 analysis/task4/collect.py              # chain CSVs, b0..b19 and b26
python3 analysis/task4/collect_narrative.py    # narrative/ CSVs (raw pgbench logs, ~90 s)
python3 analysis/task4/narrative_figures.py    # narrative/figures.tex
python3 analysis/task4/collect_pack.py         # pack/ CSVs (reads workload A from origin/main)
python3 analysis/task4/pack_figures.py         # pack/figures.tex
```

---

## 0. How to write Section 5 from this pack

**Storyline.** Six parts, in this order and with this weight:

| Part | Experiments | Depth |
| ---- | ----------- | ----- |
| 1. Copy workload A's design | `expt_b7` .. `expt_b15` | Brief. The optimisations are the A side's (T1, T5, T6, T7 and shards; Section 4 explains them). Say how each fits workload B and contrast the speedup with A's. Do not re-derive the mechanisms. |
| 2. B-specific work on T7, and the final benchmark | `expt_b16` .. `expt_b19`, replicates `expt_b20`, `expt_b21` | Detailed. This is unique to B. |
| 3. Alternative partitionings | `expt_b22` .. `expt_b25` | Medium: why none beats the final design. |
| 4. `REPEATABLE READ` | `expt_b26` | Medium: slightly faster, not kept. |
| 5. Ablation | `expt_b27` .. `expt_b41` | Statistics: the 4x4 grid, leave-one-out, interactions. |
| 6. Shard count | `expt_b42` .. `expt_b46` (+ `expt_b19`..`b21` at 4 shards) | Statistics and one mechanism. |

**The framing of Part 1.** We first copied workload A's partitioning (every
tenant table distributed by `merchant_id`, one colocation group) as a starting
point for B. We expected T7, 30% of B and not merchant-scoped, to make it a
poor fit, but it turned out to suit B well once T7 found each product's
merchant through a lookup table (`expt_b10`), because that table never
changes.

**Names.** The final design is `expt_b19`; "the final design" in numbers means
the mean of `expt_b19`, `expt_b20` and `expt_b21`. Workload A's chain is
`expt_a0`, `expt_a7` .. `expt_a15` on `origin/main`, numbered like B's:
`expt_aN` makes the same change as `expt_bN` for N = 7 .. 15. Older drafts used
other numbers (section 8).

**Do not**
- present a point with aborted clients as a measurement (sections 1, 6);
- compare absolute TPS between workloads A and B: A ran on other nodes
  (section 2); compare ratios;
- say `REPEATABLE READ` corrupts data. It never does here; it lets one
  read-only lookup see an inconsistent state (section 5);
- cite `expt_b17`'s first run (job 885153, 321.4 TPS at 1 client); it was
  replaced by a rerun (section 3.3).

**Figures and tables, ready to paste** (all compile; each takes its numbers
from the CSVs):

| Label | File | Shows | Part |
| ----- | ---- | ----- | ---- |
| `fig:b-vs-a-steps` | `pack/figures.tex` | step-by-step speedup, A against B | 1 |
| `fig:b-a-design-latency` | `narrative/figures.tex` | per-transaction latency, b0 / b7 / b8 | 1 |
| `fig:b-clients-inside` | `narrative/figures.tex` | where the 64 clients wait, b0 .. b19 | 1 |
| `fig:b-serialised` | `narrative/figures.tex` | multi-shard `UPDATE`s queue (b7, b8, b10) | 1 |
| `fig:b-t7-variants` | `narrative/figures.tex` | T7 latency and TPS of b16 .. b19 against b15 | 2 |
| `fig:b-b16-hist` | `narrative/figures.tex` | b16's bimodal T7 latency | 2 |
| `fig:b-absorption` | `narrative/figures.tex` | where T7's saving went (b17 .. b19) | 2 |
| `tab:b-final` | `pack/figures.tex` | final benchmark, 3 runs, SE, 95% CI | 2 |
| `fig:b-partitions` | `pack/figures.tex` | b22 .. b25 against the final design and b30 | 3 |
| `tab:b-ablation-grid` | `pack/figures.tex` | 4x4 heatmap, mean TPS and TPS at 64 | 5 |
| `fig:b-shards` | `pack/figures.tex` | TPS by shard count; T6 latency by shard count | 6 |

`pack/figures.tex` needs `\usepackage{colortbl}` (the heatmap) besides the
report's `pgfplots`, `xcolor`, `booktabs` and the macros `\expt`, `\txn`,
`\tbl`, `\code`. Paste the `\pgfplotsset{narr/...}` block once.
`pack/figures_preview.pdf` and `narrative/figures_preview.pdf` show them.

---

## 1. Conventions, noise and run quality

- **Protocol.** 1 coordinator + 4 workers, `xcnf[17-21]`, every B run; data
  regenerated before each client count; 600 s measured after 60 s warm-up at 1,
  4, 8, 16, 32 and 64 clients; `SERIALIZABLE` and 4 shards in the final design.
- **Metrics.** TPS = successful transactions / 600 s. **Mean TPS** = mean over
  the six client counts. **Clients inside** a transaction = its TPS x its mean
  latency (Little's law). A client count is **not valid** when pgbench exits
  non-zero or any client aborted.
- **Closed-loop model.** pgbench has no think time, so TPS = clients / R with
  R = sum over transactions of weight x mean latency. Splitting the change in R
  between two runs by transaction attributes a TPS change to transactions; it
  reproduces every measured ratio in this pack within 0.003 (column
  `pred_ratio` against `measured_ratio` in `decomposition.csv`).
- **Noise floor.** The final design ran three times, `expt_b19` on 2026-09-28
  and `expt_b20`/`expt_b21` on 2026-10-11 (`final_benchmark.csv`, `tab:b-final`):

  | Clients | 1 | 4 | 8 | 16 | 32 | 64 | Mean |
  | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
  | Mean TPS | 277.5 | 1,299.6 | 2,806.9 | 3,575.2 | 3,970.2 | 4,039.2 | 2,661.4 |
  | SE | 1.05 | 6.6 | 2.0 | 1.7 | 8.3 | 11.4 | 2.1 |
  | CV (%) | 0.66 | 0.88 | 0.12 | 0.08 | 0.36 | 0.49 | 0.14 |
  | Max/min - 1 (%) | 1.3 | 1.75 | 0.25 | 0.15 | 0.70 | 0.98 | 0.28 |

  Runs 13 days apart agree within 1.75% at every client count, so for this
  design a single run that differs by more than about 2% differs for real. This
  replaces the earlier estimate of +-5%, which came from the conditions check
  and the removed `REPEATABLE READ` replicates.
- **Midnight artefact** (`midnight_runs.csv`; full write-up
  `../ablation/README.md`). Each reset stamps every initial order
  `reset time - k days`, so the boundary day that the rollup version of T6
  scans live from `orders` is normally empty. When the reset is before midnight
  and the run after, that scan holds a whole day, about 13,700 orders, and T6
  slows. Affected: `expt_b13` at 8 clients, `expt_b24` at 16, `expt_b32` at 64
  (last 59 s only). Within-run proof: `expt_b24` at 16 clients ran 3,259 TPS
  (T6 8.5 ms) before and 2,944 (T6 13.0 ms) after, and the replaced first run
  of `expt_b17` (job 885153) at 8 clients ran 2,625 TPS with T6 at 6.8 ms
  before midnight and 2,317 TPS with T6 at 9.8 ms after. T1, T2 and T7 do not
  change.

---

## 2. Part 1: copying workload A's design (b7 .. b15), brief

**What to say.** We started B from A's design: every tenant table distributed
by `merchant_id` in one colocation group (`expt_b7`), then the same steps as
A. It worked far better than expected: mean TPS went from 7.05 (`expt_b0`) to
199.8 after two steps (`expt_b8`, 28.3x) and to 2,528.1 at `expt_b15`, 358x the
baseline. Workload A gained almost exactly the same over the same steps
(`expt_a0` 3.40 to `expt_a15` 1,217.4, 358x), but along a different path
(`fig:b-vs-a-steps`, `a_vs_b_chain.csv`):

| Step | Change | B: mean TPS x previous | A: mean TPS x previous | B: largest share at 64 | A: largest share at 64 |
| ---- | ------ | ---: | ---: | --- | --- |
| b7 / a7 | colocate by `merchant_id` | 1.56 | 1.30 | T3 41% | T3 44% |
| b8 / a8 | `merchant_id` in T3's join, T1's `UPDATE` | 18.2 | 50.3 (not valid: most clients aborted from 4 clients up) | **T7 97%** | T5 79% |
| b9 / a9 | set-based T1 | 0.99 | 1.27 | T7 97% | T5 82% |
| b10 / a10 | T7 via `product_merchant_map` | **1.59** | 1.12 | T5 89% | T5 85% |
| b11 / a11 | T5 via `order_merchant_map` | 1.07 | 1.09 | T6 66% | T1 56% |
| b12 / a12 | T6 from daily rollup | **3.01** | 1.46 | T6 43% | T1 92% |
| b13 / a13 | T1 delegated (`place_order`) | 1.11 | **1.64** | T6 51% | T1 63% |
| b14 / a14 | 8 shards | 1.87 | 1.44 | T6 41% | T1 70% |
| b15 / a15 | 4 shards | 1.20 | 1.03 | T7 46% | T1 75% |

**Why the same step pays differently: the mix.** Per transaction, the two
designs at step 15 are equally fast; at 1 client T1 takes 10.2 ms on B and 10.1
on A, T7 4.6 and 5.0 ms (`a_vs_b_latency_c1.csv`). What differs is the mix
(`mix.csv`):

| | T1 | T2 | T3 | T4 | T5 | T6 | T7 | T8 | T9 |
| - | -: | -: | -: | -: | -: | -: | -: | -: | -: |
| Workload A | 36% | 20% | 10% | 10% | 10% | 5% | 5% | 2% | 2% |
| Workload B | 10% | 10% | 5% | 5% | 10% | 10% | 30% | 10% | 10% |

Weight x latency at 1 client gives a mean response time of 4.94 ms on A, of
which T1 is 3.63 ms (73%), and 3.82 ms on B, of which T7 is 1.38 ms (36%), T1
1.02 (27%) and T6 0.84 (22%). The closed-loop model predicts 202 TPS for A and
262 for B at 1 client; measured: 203.0 and 263.1. So steps that cut T7 or T6
pay more on B, and delegating T1 pays more on A. At 64 clients B ends with no
dominant transaction (T7 46%), A with T1 at 75%; this is why only B continues
with T7 (`origin/main` dropped A's ports of b16 .. b20 for that reason).

**How the steps fit workload B** (one line each; mechanisms in Section 4):

- **b7, b8.** Colocation and `merchant_id` in every predicate make T3 and T4
  single-shard (T3 1,945 to 1.4 ms at 1 client, T4 362 to 1.0 ms;
  `fig:b-a-design-latency`). T7 barely moves (36.2 to 32.5 ms): its two
  products are drawn from all 500,000, belong to different merchants 999 times
  in 1,000 and sit on different workers 74.9% of the time (75.0% with 4 shards;
  computed from Citus's hash of `merchant_id` and checked against six placements
  in the plans).
- **The first wall on B is T7, on A it is T5; the cause is the same.** An
  `UPDATE` without the distribution column goes to every shard, and Citus lets
  only one multi-shard modification hold a shard at a time (Citus 14.1.0,
  `distributed_execution_locks.c` lines 88-137; `citus.enable_deadlock_prevention`
  defaults to on). B's T7 updates `inventory` by `inventory_id`: in `expt_b8`
  it completes 64.8-71.2 times per second whatever the load and holds 61 of 64
  clients. On A, T7 is 5% of the mix, so T5's `UPDATE orders ... WHERE order_id`
  hits the wall first (T5 79-85% of latency in a8 .. a10). `fig:b-serialised`.
- **b10: the lookup table that makes the A design fit B.** `product_merchant_map`
  maps each product to its merchant. It is filled once at load and never
  written: T9, the only writer of `products`, changes `price` only, and no
  transaction inserts or deletes products. T7 then makes four single-shard
  statements instead of six sent to all 32 shards (192 shard tasks): 32.7 to
  4.4 ms at 1 client, 885 to 9.0 ms at 64. On A the same change gives 1.12x; on
  B 1.59x, and T7's speed-up alone would have given 23.5x at 64 clients had T5
  not taken over the queue (its own rate stays at 35.5-36.3 per second from 8
  clients on, the same lock).
- **b11 .. b15** follow A: T5 routed through `order_merchant_map`, T6 from the
  rollup, T1 delegated, 8 then 4 shards. The bottleneck moves T5 -> T6 -> T7
  (`fig:b-clients-inside`). The rollup is B's biggest step after b8 (3.01x,
  against 1.46x on A) because T6 is twice A's share; 4 shards helps B more
  (1.20x against 1.03x) because T6 runs one task per shard.

---

## 3. Part 2: B-specific work on T7 (b16 .. b19) and the final benchmark

### 3.1 Why T7

At `expt_b15`, T7 is 36% of latency at 1 client and 45.6% at 64, holding 29 of
the 64 clients; removing it entirely could give at most 1 / (1 - 0.456) = 1.84x
at 64 clients. The system is near saturation there: TPS rises 2.8% from 32 to 64
clients. Each variant changes how T7 finds the two merchants
(`../narrative/t7_plans.csv`):

| Run | Change from b15 | Client statements | Worker tasks | Lookup runs on |
| --- | --- | --- | --- | --- |
| b15 | sharded map, two lookups | 4 + `BEGIN`/`COMMIT` | 4 | worker holding the map shard |
| b16 | transfer as a delegated function | 2 lookups + 1 call | 3, plus a worker-to-worker connection for a remote credit | worker |
| b17 | map as a reference table | 4 + `BEGIN`/`COMMIT` | 2 (+2 on the coordinator's copy) | coordinator |
| b18 | the two lookups merged into one statement | 3 + `BEGIN`/`COMMIT` | 4 (the lookup is 2 parallel tasks) | workers |
| b19 | b17 + b18 | 3 + `BEGIN`/`COMMIT` | 2 (+1 on the coordinator) | coordinator |

| | b15 | b16 | b17 | b18 | b19 |
| - | ---: | ---: | ---: | ---: | ---: |
| T7 mean, 1 client (ms) | 4.59 | 8.09 | 4.03 | 4.06 | 3.68 |
| T7 mean, 64 clients (ms) | 24.93 | 42.28 | 23.14 | 22.18 | 19.84 |
| TPS vs b15, 1 client | 1 | 0.794 | 1.037 | 1.029 | 1.062 |
| TPS vs b15, 64 clients | 1 | 0.686 | 1.009 | 1.006 | 1.032 |
| Mean TPS vs b15 | 1 | 0.711 | 1.027 | 1.016 | 1.051 |

`fig:b-t7-variants` plots all six client counts.

### 3.2 b16: delegating T7 made it slower (not kept)

- **Result.** Mean TPS 0.71x b15's; T7 4.6 to 8.1 ms at 1 client and 24.9 to
  42.3 ms at 64.
- **Mechanism, with direct evidence.** The call runs on the source merchant's
  worker. When the destination merchant is on another worker, that worker
  backend serves an internal Citus connection and Citus never caches its
  outgoing connections (`ShouldShutdownConnection` returns true when
  `IsCitusInternalBackend()`; Citus 14.1.0,
  `connection/connection_management.c` lines 1533-1552), so every remote credit
  opens a new connection. At 1 client T7's latency is **bimodal** with nothing
  between 4 and 7.5 ms (`fig:b-b16-hist`, `../narrative/t7_hist_c1.csv`): 24.96%
  of 37,513 calls take about 2.5 ms, the rest about 9.5 ms (25.05% of 180,536 at
  4 clients). The probability that both merchants share a worker, from Citus's
  hash, is **25.03%**. A remote credit costs about 7 ms extra. b15's distribution
  is unimodal (98% under 5.5 ms).
- **Why delegation helped T1 but not T7.** `place_order` replaced about ten
  coordinator round trips (`expt_b13`'s plan shows one task in place of ten
  subplans) and writes only the map row remotely; T7 had two routed statements
  to save and pays a new connection three times in four.

### 3.3 b17: the reference-table map

- **Rerun.** Every number here is from the rerun, job 951148 on 2026-10-15.
  The first run (job 885153) failed the conditions check, with T2, T4, T8 and
  T9, which b17 does not change, 21% faster at 1 client than in b15, and its
  8-client run crossed midnight (section 1).
- T7 falls from 4.6 to 4.0 ms at 1 client and from 24.9 to 23.1 ms at 64. TPS
  is above b15 at every client count: 3.7% at 1 client, 8.3% at 4 and 0.9% at
  64; mean 1.03x, between b18 (1.02x) and b19 (1.05x).
- **Caveat, the unchanged transactions are slower.** T2, T4, T8 and T9 are 3.3%
  slower than in b15 at 1 client (geometric mean 1.033,
  `../control_check_c1.csv`) and 7-9% slower at 64. At 64 clients the
  transactions that do not touch the map give back 0.23 ms of the 0.54 ms of
  mean response time that T7 saves (`fig:b-absorption`), so the +3.4% that T7
  alone predicts becomes +0.9%. That fits the coordinator CPU the local
  lookups use, but no CPU was measured and the rerun is 19 days after b15,
  more than the final design's replicates span, so part of it may be the
  period.
- A one-off plan observation (`t7_plans.csv`), not a mechanism: the lookup's
  task on the coordinator took 4.3-4.5 ms of coordinator time in b17, b19 and
  b20's plans against 1.3-1.7 ms for the sharded lookup, for 0.05-0.08 ms of
  work, and printed no local-execution notice with `citus.log_local_commands`
  on. It is a single cold execution; steady-state T7 is faster in b17.

### 3.4 b18: one lookup statement

T7 is 9-13% faster at every client count (22.2 against 24.9 ms at 64); TPS is
3% higher at 1 client and 0.6% at 64 (mean 1.02x). The unchanged transactions
are within 1.4% of b15.

### 3.5 b19: both, the final design

- T7 falls to 3.7 ms at 1 client and 19.8 ms at 64; TPS 6.2% above b15 at 1
  client and 3.2% at 64 (mean 1.05x). The unchanged transactions are 3.6% slower
  than in b15, so the gain is not the run's conditions. With the replicates, the
  final design is 5.3% above b15 in mean TPS (5.5% at 1 client, 3.6% at 64),
  outside the replicates' 1.75% spread.
- **Where T7's saving went** (`fig:b-absorption`,
  `../narrative/response_time_delta.csv`). At 64 clients T7 saves 1.53 ms of
  mean response time, but T1 (+0.59 ms) and T6 (+0.39) give two-thirds of it
  back, so the +10.3% that T7 alone predicts becomes +3.2%. At 1 client, where
  nothing queues, T7 alone predicts +7.7% and the measured gain is +6.2%. The
  same pattern explains b18 (+5.3% predicted, +0.6% measured at 64).

### 3.6 The final benchmark (b19, b20, b21)

`tab:b-final` gives TPS per run with mean, SE, 95% interval and CV. Per
transaction, mean of the three runs +- SE (`final_tx.csv`):

| | 1 client: mean (ms) | share | 64 clients: mean (ms) | p99 (ms) | share | clients inside |
| - | ---: | ---: | ---: | ---: | ---: | ---: |
| T1 | 10.32 +- 0.04 | 28.6% | 36.63 +- 0.40 | 146.1 | 23.2% | 14.8 |
| T6 | 8.64 +- 0.02 | 23.8% | 31.78 +- 0.19 | 85.3 | 20.1% | 12.8 |
| T7 | 3.74 +- 0.03 | 31.1% | 19.92 +- 0.04 | 52.7 | 37.8% | 24.1 |
| T5 | 1.75 +- 0.01 | 4.9% | 8.65 +- 0.02 | 33.0 | 5.5% | 3.5 |
| T3 | 1.43 +- 0.01 | 2.0% | 5.59 +- 0.03 | 26.3 | 1.8% | 1.1 |
| T2, T4, T8, T9 | 0.92-1.03 | 1.4-2.8% each | 4.43-5.68 | 22-26 | 1.4-3.6% each | 0.9-2.3 each |

Overall: p99 latency 14.2 +- 0.04 ms at 1 client and 73.7 +- 0.29 ms at 64;
7,532 +- 73 transactions retried at 64 clients (mostly T1's upsert of a hot
merchant's rollup row) and 142 serialization failures; no aborted client in any
of the three runs. Against `expt_b0`: 377x the mean TPS (2,661.4 against 7.05)
and 633x at 64 clients.

---

## 4. Part 3: alternative partitionings (b22 .. b25)

Each cell places one group of tables differently to remove one cost of
`merchant_id` (T7's lookup, or T5's map); everything else is `expt_b19`'s
(`fig:b-partitions`, `vs_final.csv`, `decomposition.csv`):

| Cell | Placement | Removes | Forced change | Mean TPS | 1 client | 64 clients |
| ---- | --------- | ------- | ------------- | ---: | ---: | ---: |
| b22 | `products` + `inventory` by `product_id` | T7's lookup | T1 not delegated | 0.87x | 0.97x | 0.78x |
| b23 | `orders` + `order_items` by `order_id` | T5's lookup and `order_merchant_map` | T3 asks every shard | 0.57x | 0.71x | 0.51x |
| b24 | `products` + `inventory` as single-shard tables on one node | T7's lookup and cross-worker commit | T1 not delegated | 0.88x | **1.04x** | 0.83x |
| b25 | `inventory` as a reference table | T7's lookup | T1 not delegated; writes to all 5 nodes | 0.11x | 0.76x | 0.075x |

All ratios are against the final design's mean. Apart from b24 at 4 clients,
every point lies outside the final design's 95% interval.

**The key comparison: placement against the T1 change.** b22, b24 and b25
move the merchant's inventory off its worker, so `place_order` cannot be
delegated and T1 is `expt_b8`'s multi-statement T1. The ablation cell `expt_b30`
is the final design with exactly that T1 and nothing else changed, so it
separates the placement from the T1 change:

| | 1 client | 64 clients | what moves (closed-loop decomposition) |
| - | ---: | ---: | --- |
| b22 / b30 | 1.014x | 1.078x | T7 -0.17 ms at 1 client, -1.74 ms at 64 (no lookup) |
| b24 / b30 | 1.089x | 1.152x | T7 -0.38 ms and -2.73 ms (no lookup, commit on one node) |
| b25 / b30 | 0.80x | 0.10x | T7 +117 ms, T2 +41, T1 +36 at 64 |
| b23 / b27 (same T1, no map) | 0.64x | 0.69x | T6 +1.25 ms at 1 client, +21.8 at 64 |

So the catalog placements (b22, b24) **are better than `merchant_id` for the
same T1**; they lose overall because `merchant_id` keeps a merchant's
customers, products, inventory and orders on one worker, which lets T1 run
whole on that worker (delegation, worth 1.22x in the ablation, section 6).

Per cell:

- **b22.** T7 3.7 to 3.1 ms at 1 client; T1 10.3 to 13.3 ms at 1 client and
  37 to 88 ms at 64 (27.5 of 64 clients); retried transactions 12,458 against
  7,532; one deadlock at 64 clients (the only one in any B run).
- **b23.** The loss is T6, not T3 (the cell's design predicted T3). With
  `orders` no longer colocated with `merchant_daily_sales`, T6's single statement
  (live boundary day `UNION ALL` rollup, grouped by merchant) cannot be pushed
  down: its plan has three distributed subplans and a final aggregation through
  intermediate results, 29.0 ms of coordinator time against 15.1 ms in b19's
  one-pass plan of 4 tasks. T6 takes 21.2 ms at 1 client (8.6) and 224 ms at 64
  (31.8), holding 46 of 64 clients. T5, now routed directly, is slower
  (1.7 to 3.7 ms at 1 client) because `orders`' primary key still leads with
  `merchant_id`: the plan shows a skip scan with 1,001 index searches. T3 rises
  only from 1.4 to 1.8 ms. Retried transactions fall to 738 at 64 (T1 writes no
  map).
- **b24.** The best 1-client result of the four (287.6 TPS, +3.6%): T7 3.7 to
  2.4 ms. From 16 clients the non-delegated T1 (85 ms at 64) and retries
  (13,873) take over; T2, T4 and T9, now all on one worker (xcnf20), are at most
  1.7 ms slower at 64. Its first run failed loading `inventory` on a Citus 14.1.0
  bug (an `INSERT ... SELECT` between colocated single-shard tables was pushed
  down with an empty distribution-column filter, `WHERE ( IS NOT NULL)`); the
  load now uses `generate_series` with the same formulas. The 16-client point is
  midnight-affected (section 1): 3,259 TPS (0.91x) before midnight.
- **b25.** Every `UPDATE` to a reference table takes an exclusive lock on its
  shard (Citus 14.1.0, `distributed_execution_locks.c` lines 149-181: replicated
  tables allow concurrency only for single-shard commutative writes such as
  `INSERT`). T1, T2 and T7, all writers of `inventory`, therefore wait in one
  queue: 413-444 ms each at 64 clients, the same signature as T1 and T5 in
  `expt_b7`. Throughput is flat at 302-352 TPS from 4 clients. Even at 1 client
  writes cost more (T2 1.0 to 2.65 ms: five copies, two-phase commit).

---

## 5. Part 4: REPEATABLE READ (b26), not kept

**Numbers** (`vs_final.csv`; b26 ran on 2026-09-28, the same day as b19):

| Clients | 1 | 4 | 8 | 16 | 32 | 64 | Mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| b26 TPS | 294.2 | 1,403.8 | 2,930.2 | 3,537.9 | 3,995.6 | 4,098.5 | 2,710.0 |
| vs final design | +6.0% | +8.0% | +4.4% | -1.0% | +0.6% | +1.5% | +1.8% |

The 1-client gain is well outside the final design's 95% interval
(273.0-282.0); the 64-client gain is at its edge (interval 3,989.9-4,088.4).
The gain comes mostly from T6, the transaction with the largest read set,
consistent with `SERIALIZABLE`'s read tracking: at 1 client every transaction
is about 3% faster than in b19 except T6, 11.9% faster (8.61 to 7.59 ms); in the
closed-loop split T6 is half of the 1-client gain and the largest part at 64.
Retries did not fall (7,924 retried transactions at 64 against 7,532 +- 73;
181 serialization failures against 142). b19's worker logs hold 18,140
write-write conflicts against 488 read/write-dependency failures, and 95% of the
write-write conflicts (17,216) are T1's upsert of a hot merchant's rollup row,
which `REPEATABLE READ` also aborts.

**What it gives up.** Citus runs PostgreSQL's serializability checks on each
node separately, with no global snapshot, so even `SERIALIZABLE` is serializable
only within a node. Every node gets the isolation level from
`default_transaction_isolation` (`run.sh` line 292), and Citus 14.1.0 forwards
the coordinator's level when it opens a transaction on a worker
(`transaction/remote_transaction.c` line 374). The comparison is therefore
per-node snapshot isolation against per-node `SERIALIZABLE`. The difference is
cycles of read-write dependencies within one node, and this workload can form
exactly one, through **T1, T9 and T4** (not T7):

1. T1 (`place_order` for merchant 7) reads product 3007's stock (100) and
   price (20.00).
2. T9 raises product 3007's price to 25.00 and commits.
3. T4 starts and reads product 3007: price 25.00, stock 100.
4. T1 decrements the stock to 98, charges 20.00 a unit, and commits.

All three run on merchant 7's worker (xcnf19 with 4 shards). T1 must precede T9
(it used the old price), T9 must precede T4 (T4 saw the new price) and T4 must
precede T1 (it did not see T1's stock change): a cycle. `SERIALIZABLE` aborts T1
or T4 and pgbench retries it; `REPEATABLE READ` lets T4 return "price 25.00,
stock 100", a state no serial order produces. It is the only such cycle: T2,
T5, T7, T8 and T9 read only the rows they write, T1 is the only writer that
reads rows others write (customer, price), and only T4 reads both what T9 writes
(price) and what T1 writes (stock).

**Why it is acceptable to note but not to keep.** The stored data is always
consistent: without T4, T1 and T9 form no cycle, and the database ends as T1
then T9. The anomaly needs T9 and T4 to hit the same product inside one T1;
from b26's rates at 64 clients (T1 410/s, T9 411/s, T4 205/s, T1 window at most
37 ms) it is expected at most about 5 x 10^-4 times per 10-minute run. But the
gain is small (+1.8% mean, +1.5% at 64 clients) and the guarantee it gives up
is the one we can state cleanly, so the final design keeps `SERIALIZABLE`.

---

## 6. Part 5: the ablation (b27 .. b41)

**Design** (`../../ablation_b19/README.md`). Four optimisations of the final
design are switched off in every combination, under `SERIALIZABLE` and 4
shards: T5 routing (off: `expt_b8`'s T5, no `order_merchant_map`), the T6 rollup
(off: `expt_b8`'s T6, no `merchant_daily_sales`), T7 routing (off: `expt_b8`'s
T7, no `product_merchant_map`) and T1 delegation (off: `expt_b8`'s
multi-statement T1). The all-on cell is the final design. 15 runs, one at a
time, 2026-10-12/13.

**The grid** (`tab:b-ablation-grid`, `ablation_cells.csv`): mean TPS as a
percentage of the final design's; dagger = not valid (aborted clients).

| T5 routing | T1 delegated | rollup on, T7 on | rollup off, T7 on | rollup on, T7 off | both off |
| --- | --- | ---: | ---: | ---: | ---: |
| on | on | **100** (final) | 17 (b28) | 20 (b29) | 10 (b34) |
| on | off | 82 (b30)+ | 18 (b35)+ | 20 (b36) | 11 (b40) |
| off | on | 85 (b27) | 17 (b31) | 21 (b32) | 11 (b37) |
| off | off | 75 (b33)+ | 10 (b38)+ | 21 (b39) | 9 (b41)+ |

(+ = not valid at some client counts.) At 64 clients the same grid reads 100,
15, 14, 8 / 72, 16, 15, 8 / 73, 13, 15, 8 / 65, 8, 17, 8.

**Leave-one-out** (`ablation_loo.csv`): how much faster the final design is
than the cell with only that optimisation off, against its step in each chain.

| Optimisation | Mean TPS | 1 client | 64 clients | Chain step on B | Chain step on A | Leave-one-out under `REPEATABLE READ` (removed grid) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| T6 rollup | 5.79x | 1.60x | 6.89x | 3.01x (b12) | 1.46x (a12) | 5.13x |
| T7 routing | 5.12x | 2.15x | 6.92x | 1.59x (b10) | 1.12x (a10) | 5.46x |
| T1 delegation | 1.22x | 1.05x | 1.39x* | 1.11x (b13) | 1.64x (a13) | 1.28x |
| T5 routing | 1.18x | **0.90x** | 1.36x | 1.07x (b11) | 1.09x (a11) | 1.17x |

(* b30 lost 2 clients at 64.) Every optimisation is worth more in the final
design than its chain step showed, because in the chain each gain was capped by
the next bottleneck. The rollup matters more under `SERIALIZABLE` than under
`REPEATABLE READ` because the unrolled T6 scan is slower (33.6 against 29.3 ms at
1 client, 942 against 709 ms at 64).

**Interactions** (`ablation_conditional.csv`; only comparisons between valid
cells are quoted).

- **Hierarchy.** With T7 routing off, T7 holds 61-63 of the 64 clients in every
  valid cell, whatever else is on. With T7 routed and the rollup off, T6 holds
  51-55 (T5, 53, if its routing is also off). With both on and T5 routing off,
  T5 holds 54-57.
- **The rollup and T7 routing need each other.** Each is worth 4.1-5.8x when
  the other is on and 1.6-1.9x when it is off. Starting from the cell with only
  T1 delegation on (`expt_b37`), T7 routing alone gives 1.58x and the rollup
  alone 1.93x; switched off from the final design they cost 5.1x and 5.8x;
  together they are worth 9.6x (final / `expt_b34`).
- **T5 routing and T1 delegation pay off only when the rollup and T7 routing
  are on** (1.09-1.22x, though these comparisons include b30 and b33, which lost
  1-2 clients at one client count); between valid cells otherwise they change
  mean TPS by at most 5%.
- **T5 routing is a trade-off, paid by T1.** Without it (`expt_b27`) throughput
  is 12% higher at 1 client and 6% at 8: T1 no longer writes
  `order_merchant_map` on a second worker (4.9 against 10.3 ms at 1 client), and
  retried transactions at 8 clients fall from 949 to 295. From 16 clients, T5 sent
  to every `orders` shard queues on the multi-shard lock (192 ms at 64, 57 of 64
  clients) and routing wins, by 36% at 64.

**Validity: a `SERIALIZABLE` interaction worth reporting.** Clients aborted
only in cells with T1 delegation off (`invalid_points.csv`): `expt_b38` and
`expt_b41` lost 2, 7, 14, 30 and 62 clients (b41: 6 at 8) at 4 .. 64 clients and
are not valid from 4 clients; `expt_b35` lost 4, 5 and 9 at 16, 32 and 64;
`expt_b30` 2 at 64; `expt_b33` 1 at 16. Every abort is T1 failing at `COMMIT`
with `could not commit transaction for shard ... on at least one active node`.
The worker logs show why: the non-delegated T1 commits in two phases from the
coordinator, and a worker rejects its `PREPARE TRANSACTION` with
`could not serialize access due to read/write dependencies among transactions`
(528 such errors across the four workers in `expt_b38`). That serialization
failure reaches pgbench as a generic commit error, which it does not retry, so
the client aborts. The delegated T1 commits on the worker and its conflicts are
retried normally; no T1-delegated cell aborts. With the rollup off as well, T6
scans the `orders` rows T1 inserts, which makes these conflicts common.

---

## 7. Part 6: shard count (b42 .. b46)

Each cell changes only `CITUS_SHARD_COUNT` in `expt_b19`'s `run.sh`
(`fig:b-shards`, `shards.csv`; 4 shards = the final design, mean of three runs).

| Shards | Run | 1 client | 4 | 8 | 16 | 32 | 64 | Mean TPS (x final) | Peak | T6 at 64 (ms) | Workers holding tenant data |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | b42 | **356.0** | 1,304.3 | 1,548.2 | 1,536.5 | 1,518.0 | 1,447.3 | 1,285.1 (0.48) | 1,548.2 @ 8 | 216 | xcnf18 only |
| 2 | b43 | 259.3 | **1,612.4** | 2,141.7 | 2,404.3 | 2,415.9 | 2,361.6 | 1,865.9 (0.70) | 2,415.9 @ 32 | 90 | xcnf18, xcnf19 |
| 4 | b19-b21 | 277.5 | 1,299.6 | **2,806.9** | **3,575.2** | **3,970.2** | **4,039.2** | **2,661.4** (1) | 4,039.2 @ 64 | 32 | all four |
| 8 | b44 | 266.4 | 1,202.8 | 2,675.4 | 3,353.1 | 3,026.5 | 2,537.9 | 2,177.0 (0.82) | 3,353.1 @ 16 | 111 | all four |
| 16 | b45 | 236.1 | 1,094.3 | 2,399.8 | 2,783.1 | 2,163.7 | 2,081.3 | 1,793.1 (0.67) | 2,783.1 @ 16 | 173 | all four |
| 32 | b46 | 215.8 | 1,085.5 | 1,997.3 | 1,236.2 | 1,465.2 | 1,269.9 | 1,211.6 (0.46) | 1,997.3 @ 8 | 272 | all four |

- **Fewer shards win at low load and lose at high load.** With 1 shard every
  distributed table, `order_merchant_map` included, is on xcnf18
  (`plan_nodes.csv`): T1 commits on one node (2.6 against 10.3 ms at 1 client) and
  so does T7 (2.6 against 3.7 ms), giving the best 1-client result of any
  experiment (+28%). But three workers do nothing, and throughput stops at about
  1,550 TPS from 8 clients. 2 shards wins at 4 clients (+24%) and stops at about
  2,400.
- **More shards cost T6, which runs one task per shard.** T6 at 64 clients:
  32 ms (4 shards), 111 (8), 173 (16), 272 (32); at 1 client it is cheapest with
  4 (8.6 ms; 13.0 with 1 shard, where one task scans everything, and 19.4 with
  32). TPS at 64 clients falls to 63%, 52% and 31% of the final design's. With 32
  shards the curve dips at 16 clients (1,236 TPS), as `expt_b13` (32 shards,
  before the reference table) did.
- **Consistent with the earlier sweeps** (`shards_earlier.csv`): on B before the
  reference table, 32 -> 8 -> 4 shards gave 1,124.5 -> 2,103.1 -> 2,528.1 mean
  TPS; on A, 826.9 -> 1,186.5 -> 1,217.4. Going from 8 to 4 shards gains 1.20x on
  B and 1.03x on A, as T6 is 10% of B's mix and 5% of A's.

---

## 8. Caveats, numbering and corrections

- **Numbering.** Old drafts called the `REPEATABLE READ` run `expt_b20` (now
  `expt_b26`), the partitioning cells `expt_b38` .. `expt_b41` (now `expt_b22` ..
  `expt_b25`), and the first ablation (around `REPEATABLE READ`, deleted;
  summary kept in `../ablation/`) `expt_b21` .. `expt_b37`. Workload A's steps
  were `expt_a1` .. `expt_a10` in an older draft; use `expt_a7` .. `expt_a15`.
- **Single runs.** Every experiment except the final design ran once. The final
  design's replicates bound run-to-run variation at about 2% for this design;
  designs with much more contention (b7, b10, b11) varied more within a run.
- **Workload A comparison.** A's runs used other node sets (`expt_a0`, `a7`,
  `a8` on `xcnf[1,3-6]`; `a9` .. `a15` on `xcnf[0-2,4,5]`); `expt_a8` is not valid
  from 4 clients up, and `expt_a10`, `a11`, `a15` lost 1-2 clients at 64. Ratios
  between consecutive A steps on the same nodes are comparable; absolute TPS
  across workloads is not.
- **Invalid points** in this pack: `expt_b30` (64), `expt_b33` (16), `expt_b35`
  (16-64), `expt_b38` and `expt_b41` (4-64).
- **Midnight-affected points:** `expt_b13` at 8 clients, `expt_b24` at 16,
  `expt_b32` at 64 (section 1).
- **Corrections to the plan for this section.** The `REPEATABLE READ` anomaly
  involves T1, T9 and T4, not T7. The shard runs are `expt_b42` .. `expt_b46`;
  4 shards is the final design (`expt_b19` .. `b21`) and 8 shards is `expt_b44`.
  The partitioning cells are `expt_b22` .. `expt_b25` (`expt_b20`, `b21` are the
  replicates).

---

## 9. Files

In this folder (built by `collect_pack.py`):

| File | Contents |
| ---- | -------- |
| `final_benchmark.csv` | b19, b20, b21 TPS per client count, mean, SD, SE, 95% CI, CV; latency, retries, serialization failures (mean, SE) |
| `final_tx.csv` | per transaction and client count: mean latency +- SE, p95, p99, share, clients inside |
| `a_vs_b_chain.csv` | b0, b7 .. b15 against a0, a7 .. a15: mean TPS, 1 and 64 clients, step and cumulative ratios, largest share, validity, A's job and nodes |
| `a_vs_b_latency_c1.csv`, `mix.csv` | per-transaction latency at 1 client (b15, a15) and the two mixes |
| `vs_final.csv` | every run from b15 on: TPS, ratio and SE distance to the final design, invalid points, retries |
| `decomposition.csv` | closed-loop split of b22 .. b26 against the final design, of b22/b24/b25 against b30 and of b23 against b27 |
| `plan_nodes.csv` | workers named in each transaction's plan (placement) |
| `ablation_cells.csv` | the 16 cells: levels, TPS and ratio per client count and mean, validity, transaction holding most clients at 64 |
| `ablation_loo.csv` | leave-one-out against chain steps (A and B) and the removed `REPEATABLE READ` grid |
| `ablation_conditional.csv` | each factor's on/off ratio for every setting of the others, with `both_valid` |
| `shards.csv`, `shards_earlier.csv` | shard sweep with T6, T1, T7 latency; earlier sweeps on B (b13 .. b15) and A (a13 .. a15) |
| `invalid_points.csv`, `midnight_runs.csv` | validity and midnight-crossing runs |
| `figures.tex`, `figures_preview.pdf` | `fig:b-vs-a-steps`, `tab:b-final`, `fig:b-partitions`, `tab:b-ablation-grid`, `fig:b-shards` |

Elsewhere: `../narrative/` (raw-log analyses: T7 histogram, latency CDFs,
response-time decomposition of b16 .. b19, plans, placement probabilities, and
six figures), `../chain_*.csv` (chain tables, `collect.py`),
`../control_check_c1.csv` (conditions check), `../ablation/` (summary of the
removed `REPEATABLE READ` grid and the midnight write-up).
