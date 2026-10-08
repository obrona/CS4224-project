### Prev: expt_b15

This experiment runs T7 (Inventory Transfer)'s routed path as one distributed
function, delegated to the worker that holds the source merchant's shard, in
the same way `expt_b13` did for T1. The two product-to-merchant lookups stay as
they were. There is no change to the schema, data distribution (4 shards, as
in `expt_b15`), indexes, the other transactions, or server parameters.

### Motivation

`expt_b15` (job-883179) reached 3897.1 TPS at 64 clients, 3.1 times `expt_b13`.
T6 dropped from the largest share of latency to the third, and T7 is now the
largest at every client count:

| Transaction           | Share at 1 client | Share at 8 clients | Share at 64 clients |
| --------------------- | ----------------- | ------------------ | ------------------- |
| T7 Inventory Transfer | 36.2%             | 37.0%              | 45.6%               |
| T1 Place Order        | 26.7%             | 28.4%              | 19.2%               |
| T6 Global Sales       | 22.1%             | 20.4%              | 17.1%               |

Throughput has levelled off: from 32 to 64 clients it rose only 2.8% while
average latency doubled. Every transaction slowed 4 to 8 times between 8 and
64 clients, including the read-only T4, which cannot be waiting on row locks
or commit flushes. That points to CPU contention somewhere, and the
transactions that do almost nothing on the workers (T2, T4, T8, T9) slowed
the most. The coordinator node, which runs pgbench and every coordinator
backend on 4 CPUs, is the likely candidate. This was not measured.

### Why T7 is slow

T7 takes 4.6 ms at 1 client, unchanged since `expt_b13`, although its work on
the shards is tiny. In `expt_b15`'s `explain.log`, each of its statements
executes in 0.09 to 0.20 ms on the shard but takes 1.1 to 1.7 ms end to end.
Its routed path sends 6 statements through the coordinator, one after
another: the two map lookups, `BEGIN`, the debit, the credit, and `COMMIT`,
which is a two-phase commit when the two merchants are on different workers.

T7 is also most of the coordinator's traffic. Counting the statements each
transaction sends to the coordinator (T7: 6; T1, T5: 2; the rest: 1) and
weighting by workload B's mix gives 2.7 statements per transaction, of which
T7 sends two-thirds (180 of 270 per 100 transactions).

### Optimisation: T7 as a distributed function

`public.transfer_inventory` is defined at the end of
`transactions/T7_inventory_transfer.sql`, inside a `\if 0 ... \endif` block
that pgbench never runs, as `place_order` is in T1's file. `run.sh` now
extracts and runs both files' blocks in `create_schema`:

```sql
SELECT create_distributed_function(
  'public.transfer_inventory(bigint, bigint, bigint, bigint, integer)',
  'p_src_merchant_id',
  colocate_with => 'merchants'
);
```

T7's routed path becomes the two unchanged lookups, then one call with no
transaction block around it:

```sql
SELECT public.transfer_inventory(
  (:t7_source_merchant_id)::bigint, (:source_product_id)::bigint,
  (:t7_dest_merchant_id)::bigint,   (:dest_product_id)::bigint,
  (:transfer_qty)::integer
);
```

The function debits the source row with the `quantity >= qty` guard and
returns `false` if that updates nothing. Otherwise it credits the destination
row and returns `true`. The debit is always local to the worker the call is
delegated to. The credit is local when the destination merchant's shard is on
the same worker, about 1 time in 4 with one shard per worker, since source and
destination products are drawn independently. Otherwise that worker sends the
credit to the destination's worker and coordinates the two-phase commit
itself.

What crosses the network per transfer:

| Case                         | `expt_b15` statements to coordinator | `expt_b15` network hops                           | This experiment: statements | This experiment: network hops                  |
| ---------------------------- | ----------------------------------- | ------------------------------------------------ | --------------------------- | ---------------------------------------------- |
| Different workers (~3 in 4)  | 6                                   | 6: 2 lookups, debit, credit, prepare, commit     | 3                           | 6: 2 lookups, call, credit, prepare, commit    |
| Same worker (~1 in 4)        | 6                                   | 5: 2 lookups, debit, credit, commit              | 3                           | 3: 2 lookups, call; everything else local      |

So in the common case the number of network hops does not change. What
changes is that the coordinator handles 3 statements per T7 instead of 6,
which takes the workload from 2.7 to 1.8 statements per transaction. This
experiment is therefore mainly a test of whether coordinator load limits
throughput. Only the same-worker case gets clearly faster on its own.

The lookups are deliberately left as two statements. They are routed
single-shard queries today, and the next change planned for them (making
`product_merchant_map` a reference table) replaces them anyway, so changing
them here would mix two effects.

The conditions for delegation are the ones in `expt_b13/optimisations.md`:
the call is a bare `SELECT f(...)` outside a transaction block, and the
distribution argument is a constant in simple query mode.

### Why T7 still behaves like expt_b0

`expt_b0`'s T7 ends in one of four ways, and each is preserved:

| `expt_b0` outcome                          | This experiment                                                           |
| ------------------------------------------ | ------------------------------------------------------------------------- |
| Same product, `ROLLBACK`                   | Checked in pgbench before the call, which is skipped. Nothing is written. |
| A product is not found, `ROLLBACK`         | The fallback path, unchanged from `expt_b15`, taken before any call.       |
| Not enough stock (debit guard), `ROLLBACK` | The function returns `false` before writing anything.                     |
| Debit and credit succeed, `COMMIT`         | The function returns `true` and commits both as one transaction.          |

- **Atomicity.** The call is one statement, so one transaction. When the
  credit is on another worker, the delegated worker commits both sides with a
  two-phase commit, so a transfer is never half-applied.
- **The credit cannot miss.** `expt_b0` could `ROLLBACK` if the credit found
  no row. Here that would need a `RAISE`, which pgbench does not retry and
  which by default stops the client. It cannot happen: `generate_data` copies
  `product_merchant_map` from `products` and gives every product exactly one
  inventory row under its own merchant, and nothing deletes inventory. The
  `RAISE` is only a guard, like the one in T1's function. `expt_b0` itself
  checks `dest_exists` earlier in the transaction, so its `ROLLBACK` on a
  failed credit is equally unreachable.
- **Isolation.** The delegated call runs at the worker's
  `default_transaction_isolation`, `SERIALIZABLE` as on every node, and Citus
  opens the remote credit with the same level. The debit's guard is part of
  the `UPDATE`, as in `expt_b15`.
- **Deadlocks.** Two opposite transfers between the same two products can
  still deadlock, exactly as before. `expt_b15` had none.

### Recording plans

`explain/T7_inventory_transfer.sql` keeps the lookup with `ANALYZE` and shows
the call with `EXPLAIN (VERBOSE)` only, outside a transaction block, as for
T1: inside one Citus would not delegate it, and running it would commit a
transfer. The debit and credit run inside the function on the worker and no
longer appear in the plan.

### What could get worse

- **Two-phase commits run by workers.** About 3 in 4 transfers now have a
  worker coordinate the commit instead of the coordinator. T1's latency
  distribution in `expt_b13` suggested that this is not cheap, but that was
  never isolated.
- **Connections between workers.** Each worker backend running a delegated
  call opens and caches a connection to the destination's worker. T1 already
  does the same for `order_merchant_map`.

### What to look at when this is run

- **`schema-create.log`.** Both `create_distributed_function` calls succeed.
- **`explain.log`.** The call's plan is one `Task` on a worker whose query is
  the call itself.
- **T7 latency at 1 client**, 4.6 ms in `expt_b15`. Expect only a small drop
  on average. The same-worker transfers (about a quarter) should form a clearly
  faster group.
- **Throughput at 32 and 64 clients**, 3792.3 and 3897.1 TPS in `expt_b15`. A
  clear rise supports the coordinator-load explanation. No change suggests
  the limit is elsewhere, most likely worker CPU.
- **Failures.** `failed_log_records` should stay 0. A non-zero count with a
  `transfer_inventory` error in `benchmark.log` would mean the credit guard
  fired.
- **`serialization_failures` and `deadlock_failures`**, 83 and 0 at 64
  clients in `expt_b15`.
- **Comparability.** Run on the same nodes as `expt_b15` (`xcnf[17-21]`).

### Note: this experiment has not been run yet
