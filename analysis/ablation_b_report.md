# Workload-B 2^5 ablation: results

Branch `ablation-b`. Cells `expt_b100`..`expt_b131`, replicates `expt_b200` and
`expt_b215`. Every number below comes from `python3 analysis/ablation.py --side b`
(and `--side a` for the A column) run on commit `fa7d727`; the CSVs and figures it
writes to `analysis/figures/ablation_b/` and `analysis/figures/ablation/` are the
source tables.

## Summary

- **T7 routing and the T6 rollup are almost the whole story on workload B.** On peak
  throughput (R_peak), T7R is ×2.77 and T6R is ×2.41. Their two-factor interaction is
  ×1.68, so together they are worth far more than the product of each alone:
  `b106` (T6R+T7R) peaks at 1211 TPS against 211 for the base `b100`.
- **Repeatable read is a small, real gain:** ×1.14 on R_peak. It grows with load: ×0.98
  (no effect) at 1 client, ×1.15 at 16.
- **T1 delegation and T5 routing do not move B's throughput.** Their R_peak intervals
  include ×1. T5 routing makes T5 4.3× faster but T1 1.6× slower, because T1 has to
  maintain the map, and the two cancel out. Delegation makes T1 3× faster, but T1 is
  only 10% of B, and every other transaction gets 1–12% slower.
- **The ranking is the reverse of workload A for T1 and T7, as the mix predicts.**
  A has 36% T1 and 5% T7; B has 10% T1 and 30% T7. On A, DEL is ×1.43 and T7R
  ×1.22; on B, DEL is ×1.06 and T7R ×2.77. T6R is large on both: ×1.92 on A and
  ×2.41 on B.
- **Best cell:** `b131` (every factor on) at 1862 TPS (8 clients), 8.8× the base. The
  best cell under SERIALIZABLE is `b114` (T6R+T7R+DEL) at 1653 TPS.
- **Effects at 32 and 64 clients cannot be estimated.** Two cells (`b105` and `b107`)
  have pgbench runs that aborted there; see "Validity".

## Scope: which A ablation this mirrors

This mirrors the **2^5 workload-A ablation** on `origin/ablation` (`expt_a100`..`a131`):
five factors (T5R, T6R, T7R, DEL, RR), Citus's default 32 shards, and SERIALIZABLE
unless RR is on. The team's **current** A ablation on `origin/ablation-rc` is a
different design, 2^4 × 3:

- 8 shards is a factor;
- RR is replaced by a third T1 mode, `fn_rc`: READ COMMITTED with a `FOR UPDATE`
  stock lock;
- it runs on `xcnf[0-2,4,5]`.

So these B results compare directly with the 2^5 A results below, but **not with
`ablation-rc`**. A B counterpart to `ablation-rc` would be about 50 more cells.

## Setup

| Item | Value |
| ---- | ----- |
| Design | 2^5 full factorial, mask bits T5R=1, T6R=2, T7R=4, DEL=8, RR=16; `ablation/README.md`, `ablation/manifest_b.csv` |
| Code | `python3 ablation/generate.py --side b`. Each cell's `transactions/` and `explain/` are byte-identical to the A cell with the same mask. `run.sh` differs only in node pin, mail user, and the `TEAM_ID`/`WORKLOAD` defaults. `expt_b100`'s transactions equal `expt_b3`'s |
| Nodes | `xcnf[17-21]`, coordinator `xcnf17`, 4 workers, 32 shards |
| Client counts | 1, 4, 8, 16, 32, 64 |
| Runs | 34 jobs (916759..916869) in a seeded random order, at most 7 concurrent, one PGPORT per slot (5536..6136). Wave 1 (7 cells) was rerun as 918553..918559 with no other cs04 job on the nodes; the rerun replaced the first run, which stays in commit `d26361a`. The decision to rerun was made before the rerun's results were seen. `ablation/run_order_b.csv` has every job id |

## Validity

pgbench aborted clients in five runs (`validity.csv`). The analysis marks those
points not valid and imputes nothing:

| Cell | Factors | Non-valid client counts |
| ---- | ------- | ----------------------- |
| `b105` | T5R+T7R | 32, 64 |
| `b107` | T5R+T6R+T7R | 64 |
| `b215` (replicate of `b115`) | T5R+T6R+T7R+DEL | 32, 64 |

The aborts have two causes, and pgbench retries neither:

- **Connection waits over 30 s.** `could not establish any connections to the node
  ... after 30000 ms` comes from the coordinator's per-worker shared pool
  (`citus.max_shared_pool_size = 300`) being exhausted at 32–64 clients.
- **Two-phase commit failures.** `could not commit transaction for shard ... on at
  least one active node` is T7's two-phase commit failing at `COMMIT` under
  SERIALIZABLE.

The worker logs show no `too many clients`. They show only serialization failures,
which pgbench does retry.

Every affected cell has T7R and SERIALIZABLE, and the aborts are intermittent. `b115`
and `b215` run the same code: `b115` ran clean once, and `b215` aborted in both of its
runs. The wave-1 rerun had no b0 jobs on the nodes and still aborted, so co-tenancy
does not explain it. This looks like a property of these designs at 32–64 clients. It
is an inference from the logs; no separate experiment tested it. The 2^5 A ablation
also has aborted points (`a104`, `a105`); their error messages were not checked
here.

**Run-to-run noise.** Replicates give the ratio of the second run to the first:

| Pair | c1 | c4 | c8 | c16 | c32 | c64 |
| ---- | -- | -- | -- | --- | --- | --- |
| `b200` / `b100` | ×1.03 | ×0.96 | ×0.97 | ×0.96 | ×0.96 | ×0.93 |
| `b215` / `b115` | ×1.06 | ×1.02 | ×1.00 | ×0.86 | n/a | n/a |

At 1 client, the transactions no factor touches (T2, T3, T4, T8, T9) differ by up to
6% (`b200`) and 10% (`b215`) between runs. That is outside the project's ~2% bar for
attributing a single-pair delta. So read single-cell comparisons (add-one,
leave-one-out) as illustrations only. The factorial effects average 16 cells against
16, and their pooled SE (0.047 log2 on R_peak, about ±7% for the 95% interval) is
consistent with that noise.

## Main effects

Each effect is the geometric-mean ratio ON/OFF over all levels of the other four
factors, with a 95% interval. The SE is pooled from the 16 three-, four- and
five-factor interactions, which are assumed to be noise (16 df). `*` marks an interval
that excludes ×1.

| Factor | R_peak | 1 client | 4 clients | 8 clients | 16 clients |
| ------ | ------ | -------- | --------- | --------- | ---------- |
| T5R | ×1.05 [0.98, 1.13] | ×1.04 [0.96, 1.13] | ×1.04 [0.98, 1.10] | ×1.03 [0.97, 1.09] | ×0.95 [0.87, 1.03] |
| T6R | ×2.41 [2.25, 2.58] * | ×1.39 [1.28, 1.51] * | ×2.03 [1.91, 2.15] * | ×2.54 [2.39, 2.69] * | ×2.53 [2.33, 2.74] * |
| T7R | ×2.77 [2.58, 2.96] * | ×2.38 [2.19, 2.58] * | ×2.41 [2.27, 2.55] * | ×2.77 [2.61, 2.93] * | ×2.35 [2.16, 2.55] * |
| DEL | ×1.06 [0.99, 1.14] | ×1.11 [1.03, 1.21] * | ×1.06 [1.00, 1.12] | ×1.04 [0.98, 1.10] | ×1.08 [0.99, 1.17] |
| RR | ×1.14 [1.07, 1.22] * | ×0.98 [0.90, 1.06] | ×1.05 [0.99, 1.11] | ×1.10 [1.03, 1.16] * | ×1.15 [1.06, 1.24] * |

Two-factor interactions on R_peak whose interval excludes ×1:

| Interaction | Ratio | Reading |
| ----------- | ----- | ------- |
| T6R:T7R | ×1.68 [1.57, 1.79] | The strongest synergy in the design. With either one off, the other bottleneck caps throughput: T7's cross-shard transfer (30% of the mix) or T6's 32-task scan (10%). Removing both is what unlocks the >1000 TPS cells. |
| T5R:T7R | ×1.08 [1.01, 1.16] | Small; at the edge of the interval. |

R_peak caveat: it is the highest TPS among a cell's valid client counts. For `b105`
(c32 and c64 not valid) and `b107` (c64 not valid), R_peak may understate the peak.
Both already peak at 8 clients among their valid points; whether c32 or c64 would
have been higher is unknown.

## Where each factor's time goes (mean latency at 1 client, ratio ON / OFF)

| Factor | T1 | T2 | T3 | T4 | T5 | T6 | T7 | T8 | T9 |
| ------ | -- | -- | -- | -- | -- | -- | -- | -- | -- |
| T5R | 1.62 | 0.97 | 0.99 | 0.99 | **0.23** | 0.99 | 0.96 | 0.98 | 0.98 |
| T6R | 1.10 | 1.01 | 1.01 | 1.00 | 1.01 | **0.32** | 1.02 | 1.00 | 1.01 |
| T7R | 0.91 | 0.88 | 0.89 | 0.92 | 0.93 | 0.98 | **0.14** | 0.89 | 0.88 |
| DEL | **0.32** | 1.10 | 1.03 | 1.03 | 1.07 | 1.01 | 1.08 | 1.10 | 1.12 |
| RR | 1.03 | 1.02 | 1.03 | 1.04 | 1.01 | 1.00 | 1.04 | 1.02 | 1.02 |

Each optimisation hits its target transaction hard (T7 is 7× faster, T5 4.3×,
DEL makes T1 3×, T6 3.1×). The latency costs show up elsewhere:

- T5R costs T1 62%, for the map insert.
- DEL costs every other transaction 1–12%. A delegated `place_order` call ties up
  worker connections, and the other transactions then wait for them. This is
  inferred, not measured.
- T7R makes the other transactions 2–12% faster, presumably because T7's
  all-shard updates no longer compete with them.

This per-transaction view is what makes the mix-dependence in the next section
predictable.

## Workload B against workload A (same 2^5 design, R_peak)

| Factor | A (36% T1, 5% T7, 5% T6) | B (10% T1, 30% T7, 10% T6) |
| ------ | ------------------------ | -------------------------- |
| T5R | ×1.01 [0.98, 1.04] | ×1.05 [0.98, 1.13] |
| T6R | ×1.92 [1.86, 1.97] * | ×2.41 [2.25, 2.58] * |
| T7R | ×1.22 [1.18, 1.26] * | ×2.77 [2.58, 2.96] * |
| DEL | ×1.43 [1.39, 1.47] * | ×1.06 [0.99, 1.14] |
| RR | ×1.09 [1.06, 1.13] * | ×1.14 [1.07, 1.22] * |
| Largest interaction | T6R:DEL ×1.33 | T6R:T7R ×1.68 |
| Best cell | `a130` (all but T5R), 1474 TPS @ 8 | `b131` (all), 1862 TPS @ 8 |
| Base | `a100` 335 TPS @ 64 | `b100` 211 TPS @ 64 |

Two points stand out:

- **The factor pairs that matter most differ.** A's dominant pair is
  T6R+DEL, its two heaviest costs; B's is T6R+T7R. In both cases the pair that
  matters is the two slowest transactions weighted by their share of the mix.
- **T5R behaves differently on the two sides.** On A it hurts at low load (×0.87
  at 1 client), because T1 is a third of the mix and pays the map insert. On B it
  is neutral.

## Recommendations

1. **For workload B, keep T6R and T7R.** On B they are the only optimisations with a
   large effect. RR adds about 14% on top. Its correctness argument is the
   teammate's (`origin/tl` `expt_a7`), and this ablation does not re-check it.
2. **T1 delegation and T5 routing are optional on B.** Neither moves throughput, so
   keep them only if they are needed for A or for latency targets.
3. **Before relying on any 32/64-client B number for a SERIALIZABLE + T7R design,
   fix the aborts.** Either raise `citus.max_shared_pool_size` / `max_connections`,
   or make T7's two-phase commit failure retryable. As it stands, those points are
   not measurable on 2 of the 8 SERIALIZABLE cells with T7R (`b105`, `b107`), nor on
   the replicate `b215`.
4. **If the comparison has to match the team's current A ablation (`ablation-rc`,
   2^4 × 3), run the B counterpart of that design.** This 2^5 run does not cover
   8 shards or the `fn_rc` T1 mode.

## Not verified

- The cause of the aborts is inferred from pgbench and PostgreSQL logs; no
  experiment changed the pool size or the retry behaviour to confirm it.
- The higher-order interactions are assumed to be noise for the error estimate.
  This is the same assumption the A analysis makes.
- The figures (`analysis/figures/ablation_b/*.png`) were generated but are not
  committed, as on the A side; regenerate them with the command below.

## Reproduce

```sh
python3 ablation/generate.py --side b      # cells (already committed)
python3 analysis/ablation.py --side b      # tables and figures -> analysis/figures/ablation_b/
python3 analysis/ablation.py --side a      # the A column above -> analysis/figures/ablation/
```

On xlogin the 1 GB virtual-memory limit breaks pandas, matplotlib and large git
operations. Run them through `srun` on a compute node outside the benchmark nodes.
