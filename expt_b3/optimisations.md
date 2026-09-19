### Prev: expt_b2

This experiment adds merchant-aware routing to T7's inventory lookups and
updates. The motivation is `expt_b2`'s result. Computing each transaction's share of total measured latency (`avg_latency_ms` x `successful_transactions`, over the
workload total) for `expt_b2` gives:

| Transaction            | Share at 1 client | Share at 64 clients |
| ---------------------- | ----------------- | ------------------- |
| T7 Inventory Transfer  | 65.9%             | 96.8%               |
| T5 Update Order Status | 18.5%             | 0.5%                |
| T6 Global Sales        | 5.1%              | 2.3%                |
| T1 Place Order         | 4.2%              | 0.3%                |
| T2 Update Inventory    | 2.4%              | 0.1%                |

T7 is the dominant cost at every client count, and every one of `expt_b2`'s
recorded transaction retries at 64 clients (35 of 35) belongs to T7. Overall
throughput barely scaled with concurrency (6.9 -> 64.4 TPS, a 9x increase for
a 64x increase in clients) while overall average latency rose to 988.6ms.

### Optimisation 1: Merchant-aware routing for T7

Added `source_merchant_id` and `dest_merchant_id`, computed directly from the
already-generated product IDs:

```
\set source_merchant_id 1 + ((:source_product_id - 1) % :NUM_MERCHANTS)
\set dest_merchant_id 1 + ((:dest_product_id - 1) % :NUM_MERCHANTS)
```

This recovers the owning merchant using the same round-robin formula the data
generator uses to assign `product_id` to a merchant
(`merchant_id + NUM_MERCHANTS * slot` in `run.sh`'s `generate_data`), so no
extra lookup query is needed to compute it. `merchant_id` was then added to
both `EXISTS` checks, both `inventory_id` lookups, and both `UPDATE`
statements, for example:

```sql
WITH debit AS (
  UPDATE inventory
  SET quantity = quantity - (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE merchant_id = (:source_merchant_id)::bigint
    AND inventory_id = (:source_inventory_id)::bigint
    AND quantity >= (:transfer_qty)::integer
  RETURNING 1
)
```

Since `inventory` is distributed and colocated by `merchant_id` (`expt_b1`),
including it in every predicate lets Citus route each statement to the one
shard it actually needs instead of scattering the lookup to every worker.

### Caveat: T7 still crosses workers when the two merchants differ

T7 still selects its source and destination products uniformly at random
across the entire dataset, so a transfer frequently still moves stock between
two merchants that live on two different workers, and Citus's distributed
transaction coordination is still required in that case. This optimisation
removes the unnecessary broadcast that occurred previously on every
transfer, including the common case where both products belong to the same
merchant and the whole transaction could otherwise stay on one worker.

### Result

At 64 clients, overall TPS rose from 64.4 (`expt_b2`) to 360.2, and overall
average latency fell from 988.6ms to 100.0ms. T7's own average latency at 64
clients is 10.1ms, and it now contributes 0 of `expt_b3`'s 384 recorded
retries. (Every unrelated transaction's latency also improved between the two
runs, including T5's, whose SQL did not change — some of this is likely
collateral relief from removing T7's cluster-wide contention, and some is
ordinary run-to-run variance on a shared Slurm cluster; the share-of-latency
and retry-attribution figures above, being normalized within a single run,
are the more reliable evidence of what this optimisation specifically did.)

A new imbalance appears, as `orders` is still updated by
`order_id` alone in T5, with no `merchant_id` predicate. At 64 clients, T5
now accounts for 333 of 384 retries (87%) and 82.4% of total latency share
(up from 8.0% at 1 client), for exactly the same underlying reason T7 used to
dominate, as the `UPDATE` cannot be routed to a single shard.
