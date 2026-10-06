# Experiment A11: READ COMMITTED with locked stock checks

## Base and change

A11 copies A10's schema, eight-shard layout, transaction mix, and all other transaction SQL. It changes the default transaction isolation on every PostgreSQL node from `serializable` to `read committed` and adds `FOR UPDATE OF i` to the inventory stock check in `place_order`. The function uses `plan_cache_mode = force_custom_plan` so its parameterized locking query is planned for the current merchant and remains routable to one Citus shard. `explain/T1_place_order.sql` plans that locking query separately, without executing it.

## Motivation

In A10 at 64 clients, T1 accounted for about 68% of summed transaction latency and averaged 80.1 ms. The run recorded 23,234 retried transactions and 1,742 serialization failures after retries. The B-side experiment B15 made the same isolation and locking changes and eliminated its recorded retries and failed transactions, but its transaction mix differs from A. A11 measures whether the benefit carries over to A's heavier T1 mix.

Under `READ COMMITTED`, two orders can otherwise both observe sufficient stock before either decrements it. Locking each inventory row during the check makes the second order wait and read the latest committed quantity. The function visits products in product ID order, maintaining a consistent T1 lock order. The later decrement therefore uses inventory rows still locked by the same transaction. The order, items, rollup, and order-to-merchant map are still written atomically by the delegated function.

The rollup upsert can wait for another T1 and add to its committed count and revenue instead of aborting on a write conflict. T2 and T7 already put their nonnegative-stock conditions in the debit `UPDATE`, so PostgreSQL rechecks them after a conflicting writer commits. B15's `optimisations.md` documents the full correctness argument for the same transaction design.

## Run and evaluation

Run from this folder so `SLURM_SUBMIT_DIR` resolves `transactions/` and `explain/` here. Keep A10 and A11 on the same five nodes and use the same benchmark settings. Check `config.txt` for `PG_ISOLATION_LEVEL=read committed` and `CITUS_SHARD_COUNT=8`. Confirm `explain.log` shows one Citus task and `LockRows` for T1's stock check. Compare throughput and T1 latency at 8, 16, 32, and 64 clients, along with `retried_transactions`, `failed_log_records`, and `pgbench_exit_code`. A failed client count is not a valid throughput comparison. Confirm no stock-check constraint errors appear in the PostgreSQL or benchmark logs.

Run as job 904118 on `xcnf[0-2,4,5]`, concurrently with `expt_a10` and `expt_a9r`. Overall TPS at 1/8/64 clients is 197.8 / 1466.1 / 2036.6 against `expt_a10`'s 196.2 / 1376.5 / 1461.5, with 0 failed and 0 retried transactions at every client count (`expt_a10` fails 1778 at 64 clients). `config.txt` records `PG_ISOLATION_LEVEL=read committed` and `CITUS_SHARD_COUNT=8`.
