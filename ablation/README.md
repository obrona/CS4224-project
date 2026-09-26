# Workload-A 2^5 factorial ablation

Five binary factors on top of the base design `expt_a100` (formerly `expt_a3`).
Every combination is one experiment, so each factor's main effect and every
interaction can be read off the 32 cells instead of off one progressive chain.

| Bit | Value | Factor | ON means | Source of the ON code |
| --- | ----- | ------ | -------- | --------------------- |
| 0 | 1 | `t5_routing` | T5 looks up `order_merchant_map`; T1 inserts the map row; `run.sh` creates, distributes, fills and truncates `order_merchant_map` | `expt_a101` (was `expt_a4`) |
| 1 | 2 | `t6_rollup` | T6 reads `merchant_daily_sales`; T1 upserts the rollup; `run.sh` creates the table and `idx_mds_period`, distributes, fills and truncates it | `expt_a102` (was `expt_a5`) |
| 2 | 4 | `t7_routing` | T7 is `expt_b7`'s; `run.sh` creates, distributes, fills and truncates `product_merchant_map` | `expt_b7` / `expt_a105` (was `expt_a8`) |
| 3 | 8 | `t1_delegation` | T1 is the `place_order` distributed function called outside a transaction block, and `run.sh` creates and distributes it; OFF is the set-based CTE T1 | `expt_a111` (was `expt_a7`) |
| 4 | 16 | `repeatable_read` | `PG_ISOLATION_LEVEL` defaults to `"repeatable read"` instead of `serializable` | `origin/tl` `expt_a7` |

Everything not controlled by a factor is exactly `expt_a100`'s: schema,
distribution, indexes, T2, T3, T4, T8, T9 and server parameters. All cells use
the A-side Slurm settings (`--nodelist=xcnf[1,3-6]`), an overridable `PGPORT`,
and, apart from the renamed `expt_a100` to `expt_a103` and `expt_a111`, record
plans in `explain.log` before the timed benchmark.

T1 follows three factors. With delegation OFF it is the set-based T1 of
`expt_a100` (neither), `expt_a101` (map insert), `expt_a102` (rollup upsert) or
`expt_a103` (both). With delegation ON it is `expt_a111`'s `place_order` (both),
or that function with step 6 (rollup upsert) and/or step 7 (map insert)
removed; nothing else in the file changes.

## Naming

- `expt_a<100 + mask>`, where mask is the sum of the enabled factors' values:
  `expt_a100` (nothing) to `expt_a131` (everything).
- `expt_a2xx` is a second run of `expt_a1xx`, with the same code:
  `expt_a200` replicates `expt_a100` and `expt_a215` replicates `expt_a115`.
  `expt_a200`'s `run.sh` is generated with every factor off rather than copied,
  so, unlike `expt_a100`'s run, it records plans.
- `manifest.csv` lists every cell and replicate with its mask, factor levels
  and whether it was renamed, generated, or is a replicate.

## Renamed cells

Seven cells already existed and were renamed with `git mv`, keeping their
results. Their contents are not edited; references to the old names inside
them are historical.

| Mask | Cell | Was |
| ---- | ---- | --- |
| 0 | `expt_a100` | `expt_a3` |
| 1 | `expt_a101` | `expt_a4` |
| 2 | `expt_a102` | `expt_a5` |
| 3 | `expt_a103` | `expt_a6` |
| 5 | `expt_a105` | `expt_a8` |
| 11 | `expt_a111` | `expt_a7` |
| 15 | `expt_a115` | `expt_a9` |

## Regenerating

```sh
python3 ablation/generate.py
```

This rewrites `run.sh`, `transactions/`, `explain/T*.sql` and
`optimisations.md` of the 25 generated cells and the two replicates, and
`manifest.csv`. It never writes to a renamed cell, and it refuses to change the
code of a directory that already has `slurm-results/`. Each generated
directory is a standalone experiment: submit it like any other, nothing reads
the generator at run time.

To compare the generator's output for any mask with an existing directory:

```sh
python3 ablation/generate.py --out /tmp/ablation --masks 0,1,2,3,5,11,15
```

## Template

- `template/run.sh` is `expt_a115`'s `run.sh` with markers. Lines between
  `# @ablation-begin F` and `# @ablation-end F` are kept only when factor `F`
  is ON (`!F`: only when OFF). `@{F:text}` inside a line becomes `text` only
  when `F` is ON; it builds the `TRUNCATE` list. Generated files contain no
  markers.
- `template/transactions/` and `template/explain/`: `<T>.sql` is shared by
  every cell; `<T>/<variant>.sql` is chosen per cell. Each variant is a copy of
  the file named in the factor table, except `T1_place_order/fn_none.sql`,
  `fn_map.sql` and `fn_rollup.sql`, which are `fn_both.sql` with steps removed.
  Every delegation variant issues the same call, so all of them share
  `explain/T1_place_order/fn.sql`.
- Against the renamed cells, generated output differs only in the native
  EXPLAIN step (`expt_a100` to `expt_a103`, `expt_a111`) and in the order of
  the `merchant_daily_sales` and `order_merchant_map` `create_distributed_table`
  calls (`expt_a103`, `expt_a111`), which follows `expt_a115`. All tables are
  created before any is distributed, and `merchant_daily_sales` colocates with
  `merchants`, which is distributed first, so the order has no effect.
