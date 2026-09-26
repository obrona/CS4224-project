### Prev: expt_a6

This experiment runs T1 (Place Order) as one distributed function, which Citus
delegates whole to the worker that holds the merchant's shards. The new order
and item ids are still drawn first, in a separate coordinator-only statement.
It is a port of `expt_b7`: `T1_place_order.sql` is identical to `expt_b7`'s,
because `expt_a6`'s T1 is identical to `expt_b6`'s. There is no change to the
schema, data distribution, indexes, the other transactions, or server
parameters carried over from `expt_a6`.

### Motivation

T1 is 36% of workload A and already the largest share of latency at 1 and 8
clients in `expt_a3` (54% and 47%). `expt_a3`'s set-based rewrite made T1
slower, not faster: 9.5 ms in `expt_a2` against 17.2 ms in `expt_a3` at
1 client. `expt_a4` and `expt_a5` each add a write to it.

### Why T1 is slow

`expt_b6`'s `explain.log` shows T1's main statement is not routed. Citus plans
it recursively: every CTE becomes its own distributed subplan, executed one
after another, each passing its rows to the next as an intermediate result.
`inserted_order` and `inserted_items` both show
`INSERT/SELECT method: pull to coordinator`. With the `order_merchant_map`
insert, the rollup upsert and the two-phase commit, T1 is roughly a dozen
sequential coordinator round trips. `expt_a3` onwards run the same statement,
so the same plan applies here (assumed from `expt_b6`; not re-recorded on the
A side).

### Optimisation: T1 as a distributed function

`public.place_order` is defined at the end of `transactions/T1_place_order.sql`
inside a `\if 0 ... \endif` block, which pgbench always skips. `run.sh`
extracts the lines between the two markers in `create_schema` and runs them
once with psql after the tables are distributed. They create the function and
distribute it by `p_merchant_id`, colocated with `merchants`:

```sql
SELECT create_distributed_function(
  'public.place_order(bigint, bigint, bigint, integer, bigint[], integer[], bigint[])',
  'p_merchant_id',
  colocate_with => 'merchants'
);
```

T1 is now two statements with no transaction block:

```sql
SELECT nextval('benchmark_order_id_seq') AS order_id, ... \gset t1_

SELECT public.place_order(
  (:merchant_id)::bigint, (:customer_id)::bigint, (:t1_order_id)::bigint,
  (:item_count)::integer,
  ARRAY[...product ids...], ARRAY[...quantities...], ARRAY[...item ids...]
);
```

The function checks the customer, checks every distinct product's existence
and combined stock, and returns `false` before writing anything if a check
fails. Otherwise it decrements inventory in `product_id` order, inserts the
order and its items, upserts `merchant_daily_sales`, and inserts the
`order_merchant_map` row. Everything but the map row is on the merchant's
worker; the worker coordinates the two-phase commit for the map row itself.

The conditions Citus requires for delegation (no transaction block, a bare
`SELECT f(...)`, a constant distribution argument, metadata on the workers,
schema-qualified names) and the argument that T1 still produces the
baseline's rows under `SERIALIZABLE` are in `expt_b7/optimisations.md` and
apply unchanged.

### What to look at when this is run

- **`schema-create.log`.** `create_distributed_function` succeeds, and every
  worker shows `hasmetadata` and `metadatasynced` as `t`.
- **T1 latency at 1 client** against `expt_a6`. If it stays close to
  `expt_a6`'s, delegation is not happening; unlike `expt_b7`, this experiment
  does not record plans, so that would need checking separately.
- **`serialization_failures` and `deadlock_failures`.** A faster T1 means more
  overlap on hot merchants' inventory and rollup rows.
- **Comparability.** Pinned to `xcnf[1,3-6]`, the same nodes as `expt_a0` to
  `expt_a6`.
