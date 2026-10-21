### Prev: expt_a17

The final design, `expt_a17`, with 16 shard(s) per distributed table instead
of 4 (`CITUS_SHARD_COUNT` defaults to 16). Nothing else changes. Part of the
shard-count study around the final design, as `expt_b42` to `expt_b46` are
for workload B (1, 2, 8, 16 and 32 shards); `expt_a17_1` and `expt_a17_2`,
running in the same batch, are the 4-shard reference.

Run: job 979122, team id 604, on `xcnf[0-2,4,5]`, in the same batch as `expt_a17_1` and `expt_a17_2` (jobs 979011, 979012) and `expt_a15_3` (979013).
