### Prev: expt_b300 (grid base)

Cell 318 (T1 mode 1 `fn`, mask 2) of the 2^4 x 2 workload-B ablation (`ablation/README.md`, "Workload B"); every cell's factor levels are in `ablation/manifest_b.csv`.

Renamed from `expt_b110` of the 2^5 workload-B ablation (branch `ablation-b`; bits T5R=1 T6R=2 T7R=4 DEL=8 RR=16, Citus's default 32 shards), where it was mask 10: DEL=1 and RR=0, which is this grid's T1 mode `fn` with `shards8` off. Its result (`slurm-results/`, `citus-*.out`, `citus-*.err`) was added on that branch in d26361a; the raw logs are gzipped here (`ablation/README.md`, "Stored results").

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
| `t6_rollup` (bit 2) | T6 rollup: T6 reads `merchant_daily_sales`; T1 upserts the rollup row; `run.sh` creates it with `idx_mds_period`, distributes, fills and truncates it |
| `t1_mode=fn` (m=1) | T1 delegation: T1 is the `place_order` distributed function, called outside a transaction block; `run.sh` creates and distributes the function |

T1's `place_order` is `expt_a323`'s with step 7 (`order_merchant_map` insert) removed from the function body. The signature, the pgbench-side statements and the rest of the body are unchanged, and the remaining steps keep the original numbering.
