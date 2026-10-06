# Workload-A 2^4 x 3 factorial ablation

Four binary factors and a three-level T1 mode on one shared reference
configuration. Every combination is one experiment, so each factor's main
effect and every interaction can be read off the 48 cells instead of off one
progressive chain.

| Factor | Levels | ON / level means | Source of the code |
| ------ | ------ | ---------------- | ------------------ |
| `t5_routing` | bit 1 | T5 looks up `order_merchant_map`; T1 inserts the map row; `run.sh` creates, distributes, fills and truncates `order_merchant_map` | `expt_a101` (was `expt_a4`) |
| `t6_rollup` | bit 2 | T6 reads `merchant_daily_sales`; T1 upserts the rollup; `run.sh` creates the table and `idx_mds_period`, distributes, fills and truncates it | `expt_a102` (was `expt_a5`) |
| `t7_routing` | bit 4 | T7 is `expt_b7`'s; `run.sh` creates, distributes, fills and truncates `product_merchant_map` | `expt_b7` / `expt_a105` (was `expt_a8`) |
| `shards8` | bit 8 | `run.sh` runs `SET citus.shard_count = 8` (`CITUS_SHARD_COUNT`) in the session that distributes every table, instead of Citus's default 32, and records it in `config.txt` | `expt_a331` (was `expt_a10`) |
| `t1_mode` | m = 0 `set` | T1 is the set-based CTE T1 inside `BEGIN`/`COMMIT` | `expt_a100` to `expt_a103` |
| | m = 1 `fn` | T1 is the `place_order` distributed function, called outside a transaction block; `run.sh` creates and distributes it | `expt_a111` (was `expt_a7`) |
| | m = 2 `fn_rc` | `fn`, plus `PG_ISOLATION_LEVEL` defaults to `read committed` instead of `serializable`, the stock check takes `FOR UPDATE OF i`, and the function sets `plan_cache_mode = force_custom_plan` | `expt_a347` (was `expt_a11`) |

T1 follows `t5_routing`, `t6_rollup` and `t1_mode`. With m = 0 it is the
set-based T1 of `expt_a100` (neither), `expt_a101` (map insert), `expt_a102`
(rollup upsert) or `expt_a103` (both). With m = 1 or 2 it is the mode's
`place_order` with both steps, or that function with step 6 (rollup upsert)
and/or step 7 (map insert) removed; nothing else in the file changes.

Why the T1 mode is one three-level factor rather than two bits: READ COMMITTED
is only valid together with the `FOR UPDATE OF i` stock lock, and only the
delegated function has that lock. Neither T1 puts a stock predicate on its
inventory decrement, so under READ COMMITTED without the lock two orders can
both pass the stock check before either decrements: the second is accepted
against stock that is gone and is stopped only by `CHECK (quantity >= 0)`, as
an error rather than a clean rejection. "Set-based T1 under READ COMMITTED"
is therefore not a valid cell, and RC + lock is a level of T1, not an
independent factor. `expt_a347/optimisations.md` (was `expt_a11`) has the
full argument.

Everything not controlled by a factor is the shared reference of
`template/run.sh`, which is `expt_a9r`'s `run.sh` with markers: `expt_a100`'s
schema, distribution, indexes, T2, T3, T4, T8, T9 and server parameters;
`--nodelist=xcnf[0-2,4,5]`; `TEAM_ID` default 4 and
`PGPORT=$((10#${TEAM_ID} + 5432))` with no override, so concurrent jobs set
`TEAM_ID` (4, 104, 204, ...); plans recorded in `explain.log` before the timed
benchmark.

## Naming

- `expt_a<300 + 16*m + mask>`, where mask is the sum of the enabled bits:
  `expt_a300` to `expt_a315` (m = 0), `expt_a316` to `expt_a331` (m = 1),
  `expt_a332` to `expt_a347` (m = 2).
- `expt_a4xx` is a second run of `expt_a3xx`, with the same code:
  `expt_a400` replicates `expt_a300` and `expt_a431` replicates `expt_a331`.
  A replicate of a generated cell is generated the same way; a replicate of a
  renamed cell copies its `run.sh`, `transactions/` and `explain/`.
- `manifest.csv` lists every cell and replicate with its factor levels
  (`t1_mode` is `set`, `fn` or `fn_rc`) and whether it was renamed,
  generated, or is a replicate.

## Renamed cells

Three cells already existed and are renamed with `git mv`, keeping their
results. Their contents are not edited; references to the old names inside
them are historical.

| Cell | m | Mask | Was |
| ---- | - | ---- | --- |
| `expt_a323` | 1 | 7 (t5, t6, t7) | `expt_a9r` |
| `expt_a331` | 1 | 15 (all) | `expt_a10` |
| `expt_a347` | 2 | 15 (all) | `expt_a11` |

## Regenerating

```sh
python3 ablation/generate.py
python3 ablation/validate.py
```

The first rewrites `run.sh`, `transactions/`, `explain/T*.sql` and
`optimisations.md` of the 45 generated cells and the two replicates, and
`manifest.csv`. It never writes to a renamed cell or to the archive below,
and it refuses to change the code of a directory that already has
`slurm-results/`. Each generated directory is a standalone experiment: submit
it like any other, nothing reads the generator at run time.

The second checks that the generator reproduces the three renamed cells byte
for byte, the structure and template-file selection of every cell, that
cells one factor step apart differ only in that factor's lines and files, and
that the archive is never an output. It exits non-zero on failure.

To write the generator's output for any cell ids elsewhere, e.g. to compare
with an existing directory:

```sh
python3 ablation/generate.py --out /tmp/ablation --cells 323,331,347
```

## Template

- `template/run.sh`: lines between `# @ablation-begin F` and
  `# @ablation-end F` are kept only when factor `F` is ON (`!F`: only when
  OFF). `@{F:text}` inside a line becomes `text` only when `F` is ON; it
  builds the `TRUNCATE` list. `F` is a bit name, `t1_delegation` (m >= 1) or
  `rc_lock` (m = 2). Generated files contain no markers.
- `template/transactions/` and `template/explain/`: `<T>.sql` is shared by
  every cell; `<T>/<variant>.sql` is chosen per cell. T1 transactions:
  `set_<level>.sql` for m = 0, `fn_both.sql` for m = 1 and `fn_both_rc.sql`
  (`expt_a11`'s T1) for m = 2, where `generate.py` removes step 6 and/or 7
  from the function for the other `t5_routing`/`t6_rollup` levels. T1 explain:
  `set_<level>.sql`, `fn.sql` (every m = 1 level issues the same call) or
  `fn_rc.sql` (`expt_a11`'s, which also plans the locking stock check).
  T5, T6, T7: `on.sql`/`off.sql` by their own factor. `shards8` changes only
  `run.sh`.

## Archive: the earlier 2^5 grid

`expt_a100` to `expt_a131`, `expt_a200` and `expt_a215` are the earlier 2^5
ablation (factors `t5_routing`, `t6_rollup`, `t7_routing`, `t1_delegation`,
`repeatable_read`) run on `xcnf[1,3-6]`. They are not part of the current grid
and are not comparable with it, since the node set and run configuration
differ. They are kept as-is; the generator never writes to them.

## Stored results

Each run's raw `pgbench -l` transaction logs (`benchmark-results/logs/*`) and
PostgreSQL server logs (`xcnf*-postgresql.log`) are committed gzipped, which
takes the 50 cells of the 2^4 x 3 grid from 15.3 GB to 3.7 GB. Read them with
`zcat`. Summaries, per-client result text, `metrics-c*` and `config.txt` stay
uncompressed, and `analysis/ablation.py` reads only those.
