### Prev: expt_b300 (grid base)

Cell 321 (T1 mode 1 `fn`, mask 5) of the 2^4 x 3 workload-B ablation (`ablation/README.md`, "Workload B"); every cell's factor levels are in `ablation/manifest_b.csv`.

Renamed from `expt_b113` of the 2^5 workload-B ablation (branch `ablation-b`; bits T5R=1 T6R=2 T7R=4 DEL=8 RR=16, Citus's default 32 shards), where it was mask 13: DEL=1 and RR=0, which is this grid's T1 mode `fn` with `shards8` off. Its result (`slurm-results/`, `citus-*.out`, `citus-*.err`) was added on that branch in fa7d727; the raw logs are gzipped here (`ablation/README.md`, "Stored results").

Its `run.sh`, `transactions/` and `explain/` are kept as run. They are byte-identical to `ablation/generate.py --side b`'s output for this cell except for `run.sh`'s PGPORT lines, which as run are

```sh
# PGPORT may be overridden so several experiments can share the pinned node set
# concurrently; each needs its own port because they run on the same hosts.
# Unset, it is exactly the per-team port the project spec assigns.
PGPORT="${PGPORT:-$((10#${TEAM_ID} + 5432))}"
```

where the generator writes

```sh
# Port derived from the team ID; concurrent jobs use TEAM_ID 4, 104, 204, ...
PGPORT=$((10#${TEAM_ID} + 5432))
```

Every job of the 2^5 workload-B ablation was submitted with `PGPORT` unset (one `TEAM_ID` per port slot, 104 to 704), so the port was `TEAM_ID + 5432` under both. `ablation/validate.py --side b` checks that nothing else differs.

Enabled factors:

| Factor | Description |
| ------ | ----------- |
| `t5_routing` (bit 1) | T5 routing: T5 looks up `order_merchant_map`; T1 inserts the map row; `run.sh` creates, distributes, fills and truncates `order_merchant_map` |
| `t7_routing` (bit 4) | T7 routing: T7 is `expt_b7`'s: it looks up `product_merchant_map` before `BEGIN` and routes its two `UPDATE`s; `run.sh` creates, distributes, fills and truncates `product_merchant_map` |
| `t1_mode=fn` (m=1) | T1 delegation: T1 is the `place_order` distributed function, called outside a transaction block; `run.sh` creates and distributes the function |

T1's `place_order` is `expt_a323`'s with step 6 (`merchant_daily_sales` upsert) removed from the function body. The signature, the pgbench-side statements and the rest of the body are unchanged, and the remaining steps keep the original numbering.
Step 4 still has `RETURNING total_amount, created_at INTO v_order_total, v_created_at`, although only step 6 read them.
