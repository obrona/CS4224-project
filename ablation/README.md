# Workload-A 2^4 x 3 factorial ablation

Four binary factors and a three-level T1 mode on one shared reference
configuration. Every combination is one experiment, so each factor's main
effect and every interaction can be read off the 48 cells instead of off one
progressive chain.

| Factor | Levels | ON / level means |
| ------ | ------ | ---------------- |
| `t5_routing` | bit 1 | T5 looks up `order_merchant_map`; T1 inserts the map row; `run.sh` creates, distributes, fills and truncates `order_merchant_map` |
| `t6_rollup` | bit 2 | T6 reads `merchant_daily_sales`; T1 upserts the rollup; `run.sh` creates the table and `idx_mds_period`, distributes, fills and truncates it |
| `t7_routing` | bit 4 | T7 is `expt_b7`'s; `run.sh` creates, distributes, fills and truncates `product_merchant_map` |
| `shards8` | bit 8 | `run.sh` runs `SET citus.shard_count = 8` (`CITUS_SHARD_COUNT`) in the session that distributes every table, instead of Citus's default 32, and records it in `config.txt` |
| `t1_mode` | m = 0 `set` | T1 is the set-based CTE T1 inside `BEGIN`/`COMMIT` |
| | m = 1 `fn` | T1 is the `place_order` distributed function, called outside a transaction block; `run.sh` creates and distributes it |
| | m = 2 `fn_rr` | `fn`, plus `PG_ISOLATION_LEVEL` defaults to `repeatable read` instead of `serializable` |

T1 follows `t5_routing`, `t6_rollup` and `t1_mode`. With m = 0 it is the
set-based T1 with neither, the map insert, the rollup upsert or both
(`template/transactions/T1_place_order/set_<level>.sql`). With m = 1 or 2 it
is `expt_a323`'s `place_order` with both steps, or that function with step 6
(rollup upsert) and/or step 7 (map insert) removed; nothing else in the file
changes.

**The `fn_rr` level.** m = 2 is the delegated T1 of m = 1 under REPEATABLE
READ, the isolation level `expt_b14` runs under. Its `transactions/` and
`explain/` are byte-identical to the m = 1 cell with the same mask, and its
`run.sh` differs only in the `PG_ISOLATION_LEVEL` default. `run.sh` writes
that value to every node's `default_transaction_isolation`, so it applies to
every transaction of the workload, not only T1. The project team made
REPEATABLE READ a level of the T1 mode rather than a binary factor: the grid
has no set-based T1 under REPEATABLE READ, so its effect (`fn_rr` against
`fn`) is measured only with delegation.

**Replaced level.** Until 2026-10-08 the grid's m = 2 was `fn_rc`, the
delegated function under READ COMMITTED with a `FOR UPDATE` stock lock and
`plan_cache_mode = force_custom_plan`. It was dropped on 2026-10-08 by
decision of the project owner, with its cells, template files and generator
support; its code and results are in git history at `f2b08264`, under the
cell names `expt_a332` to `expt_a347` and `expt_b332` to `expt_b347` that the
`fn_rr` cells now use. `run_order.csv` and `run_order_b.csv` are records of
what was submitted: every row already in them for those names (A: job ids up
to 909389, B: up to 919242) is an `fn_rc` job, not an `fn_rr` one.

Everything not controlled by a factor is the shared reference of
`template/run.sh`, which is `expt_a323`'s `run.sh` with markers: the
workload-A base design's (formerly `expt_a3`, see git history) schema,
distribution, indexes, T2, T3, T4, T8, T9 and server parameters;
`--nodelist=xcnf[0-2,4,5]`; `TEAM_ID` default 4 and
`PGPORT=$((10#${TEAM_ID} + 5432))` with no override, so concurrent jobs set
`TEAM_ID` (4, 104, 204, ...); plans recorded in `explain.log` before the timed
benchmark.

## Naming

- `expt_a<300 + 16*m + mask>`, where mask is the sum of the enabled bits:
  `expt_a300` to `expt_a315` (m = 0), `expt_a316` to `expt_a331` (m = 1),
  `expt_a332` to `expt_a347` (m = 2).
- `expt_a<id>_<k>` is the k-th additional run (k = 1, 2, ...) of
  `expt_a<id>`, with the same code: `expt_a300_1` replicates `expt_a300`, and
  `expt_a331_1` and `expt_a331_2` replicate `expt_a331` ("Batch drift"). A
  replicate of a generated cell is generated the same way; a replicate of an
  existing cell copies its `run.sh`, `transactions/` and `explain/`.
- `manifest.csv` lists every cell and replicate with its factor levels
  (`t1_mode` is `set`, `fn` or `fn_rr`) and its source: `generated`,
  `existing` or `replicate of expt_a<id>`.
- Each combination of optimisations is one experiment, its grid cell;
  replicates are reruns of that cell, not other combinations.

## Existing cells

Two cells were run before the generator existed: `expt_a323` (m = 1, mask 7:
t5, t6, t7) and `expt_a331` (m = 1, mask 15).
They keep their results and their hand-written `optimisations.md`, which
records under which name each was first run.

## Batch drift

Every m = 2 cell is a new run and every m <= 1 cell ran before them, so any
drift between the earlier runs and the `fn_rr` batch is confounded with RR
(and with the `fn_rr` half of DEL). `expt_a331_2` reruns `expt_a331` in the
`fn_rr` batch: its difference from `expt_a331` and `expt_a331_1` measures that
drift, on top of run-to-run variation. Like `expt_a331_1`, it copies
`expt_a331`'s `run.sh`, `transactions/` and `explain/`.

## Regenerating

```sh
python3 ablation/generate.py
python3 ablation/validate.py
```

The first rewrites `run.sh`, `transactions/`, `explain/T*.sql` and
`optimisations.md` of the 46 generated cells and the three replicates, and
`manifest.csv`. It never writes to an existing cell, and it refuses to change
`run.sh`, `transactions/` or `explain/` of a directory that already has
`slurm-results/` (its `optimisations.md` may still be rewritten). Each
generated directory is a standalone experiment: submit it like any other,
nothing reads the generator at run time.

The second checks that the generator reproduces the two existing cells byte
for byte, the structure and template-file selection of every cell, that
cells one factor step apart differ only in that factor's lines and files
(m = 1 to 2: only the `PG_ISOLATION_LEVEL` line), the generator's outputs and
replicate names, and that a directory with `slurm-results/` keeps its code.
It exits non-zero on failure.

To write the generator's output for any cell ids elsewhere, e.g. to compare
with an existing directory:

```sh
python3 ablation/generate.py --out /tmp/ablation --cells 323,331
```

## Template

- `template/run.sh`: lines between `# @ablation-begin F` and
  `# @ablation-end F` are kept only when factor `F` is ON (`!F`: only when
  OFF). `@{F:text}` inside a line becomes `text` only when `F` is ON; it
  builds the `TRUNCATE` list. `F` is a bit name, `t1_delegation` (m >= 1) or
  `repeatable_read` (m = 2; its blocks hold only the `PG_ISOLATION_LEVEL`
  line). Generated files contain no markers.
- `template/transactions/` and `template/explain/`: `<T>.sql` is shared by
  every cell; `<T>/<variant>.sql` is chosen per cell. T1 transactions:
  `set_<level>.sql` for m = 0 and `fn_both.sql` (`expt_a323`'s T1) for
  m = 1 and 2, where `generate.py` removes step 6 and/or 7 from the function
  for the other `t5_routing`/`t6_rollup` levels. T1 explain: `set_<level>.sql`
  or `fn.sql` (every delegated level issues the same call).
  T5, T6, T7: `on.sql`/`off.sql` by their own factor. `shards8` changes only
  `run.sh`.

## Stored results

Each run's raw `pgbench -l` transaction logs (`benchmark-results/logs/*`) and
PostgreSQL server logs (`xcnf*-postgresql.log`) are committed gzipped, which
took the 50 A directories committed at `f2b08264` (with the `fn_rc` cells)
from 15.3 GB to 3.7 GB. Read them with
`zcat`. Summaries, per-client result text, `metrics-c*` and `config.txt` stay
uncompressed, and `analysis/ablation.py` reads only those.

## Workload B

The same grid on workload B: cells `expt_b<300 + 16*m + mask>` with the same
factors, bits and T1 modes, listed in `manifest_b.csv` (the columns of
`manifest.csv`; `source` is `generated`, `renamed from expt_b1xx` or
`replicate of expt_b<id>`).

```sh
python3 ablation/generate.py --side b
python3 ablation/validate.py --side b
```

- **Code.** A B cell's `transactions/` and `explain/` are byte-identical to
  the A cell with the same id. Its `run.sh` is the rendered template with
  exactly three substitutions, each of which must match exactly once or the
  generator fails: the A node-pin comment and `--nodelist=xcnf[0-2,4,5]`
  become the B-side comment and `--nodelist=xcnf[17-21]`; `--mail-user`
  becomes `e1334269@u.nus.edu`; `WORKLOAD` defaults to `B`. `TEAM_ID` defaults
  to 4 and `PGPORT` is derived from it, as on A.
- **Node set.** Every B cell is pinned to `xcnf[17-21]`, disjoint from A's
  `xcnf[0-2,4,5]`, so the two workloads can run at the same time without
  sharing hardware. Compare B runs only with B runs.
- **Reused runs.** The earlier 2^5 workload-B ablation (branch `ablation-b`;
  bits T5R=1 T6R=2 T7R=4 DEL=8 RR=16, Citus's default 32 shards) has 16 cells
  that are exactly cells of this grid: DEL = 0 / 1 with RR = 0 is T1 mode
  `set` / `fn` with `shards8` off. They and their two replicates were moved
  here with their results, under their grid names:

  | 2^5 name | grid name | |
  | -------- | --------- | - |
  | `expt_b100` .. `expt_b107` | `expt_b300` .. `expt_b307` | m = 0, mask 0..7 |
  | `expt_b108` .. `expt_b115` | `expt_b316` .. `expt_b323` | m = 1, mask 0..7 |
  | `expt_b200` | `expt_b300_1` | replicate of `expt_b300` |
  | `expt_b215` | `expt_b323_1` | replicate of `expt_b323` |

  They are valid grid runs because they ran this grid's code on this node set.
  `validate.py --side b` (check 1) shows that their `transactions/` and
  `explain/` are byte-identical to the generator's output, and so is `run.sh`
  except for the PGPORT lines: the 2^5 `run.sh` let `PGPORT` be overridden
  (`PGPORT="${PGPORT:-$((10#${TEAM_ID} + 5432))}"`, with a three-line
  comment) where the generator writes `PGPORT=$((10#${TEAM_ID} + 5432))`.
  Every 2^5 job was submitted with `PGPORT` unset (one `TEAM_ID` per port
  slot, 104 to 704), so the port was the same. The generator never writes
  their `run.sh`, `transactions/` or `explain/`, only their
  `optimisations.md`, which names the 2^5 cell and the commit on `ablation-b`
  that added the result (`d26361a`, or `fa7d727` for `expt_b105` to
  `expt_b107`, `expt_b113` and `expt_b215`, wave-1 cells that were rerun
  there). The 2^5 manifest, run order and analysis stay on `ablation-b`, and
  so do its RR = 1 cells (`expt_b116` to `expt_b131`). Those with DEL = 0
  (`expt_b116` to `expt_b123`, set-based T1 under REPEATABLE READ) have no
  place in this grid. Those with DEL = 1 (`expt_b124` to `expt_b131`) are
  `fn_rr` cells with `shards8` off (`expt_b332` to `expt_b339`): their
  `transactions/` and `explain/` are byte-identical to the generator's
  output, and `run.sh` differs only in the PGPORT lines, as the reused cells'
  does. They are not reused, so that every `fn_rr` cell runs in one batch:
  mixing them in would split the RR contrast across two batches, against the
  one drift probe (`expt_b331_2`) that this batch has. It costs 8 runs.
- **New runs.** The other 32 cells are generated: `shards8` on for m = 0 and
  1 (`expt_b308` to `expt_b315`, `expt_b324` to `expt_b331`) and every
  m = 2 cell (`expt_b332` to `expt_b347`), plus three replicates:
  `expt_b331_1`, which mirrors `expt_a331_1`, `expt_b300_2` and
  `expt_b331_2` ("Batch drift").
- **Batch drift.** The 16 reused cells are exactly the cells with `shards8`
  off and m <= 1, the 16 cells with `shards8` on and m <= 1 are the second
  batch, and the 16 `fn_rr` cells are a third. Any difference between the
  2^5 batch and the second batch is fully confounded with `shards8` among the
  m <= 1 cells, and any difference between the earlier batches and the
  `fn_rr` batch with RR (and the `fn_rr` half of DEL), so on B every contrast
  involving SH8 or RR also carries batch drift. `expt_b300_2` reruns
  `expt_b300` in the second batch: its difference from `expt_b300` and
  `expt_b300_1` measures that drift, on top of run-to-run variation. Its
  `run.sh` is the generator's, so it differs from `expt_b300`'s only in the
  PGPORT lines. `expt_b331_2` reruns `expt_b331` in the `fn_rr` batch: its
  difference from `expt_b331` and `expt_b331_1` measures that batch's drift.
- **Stored results and run order.** The reused runs' raw logs are gzipped as
  on A ("Stored results"; 2.46 GB to 0.93 GB for the 18 directories).
  `run_order_b.csv` has `run_order.csv`'s columns and lists each new B job as
  it is submitted.
