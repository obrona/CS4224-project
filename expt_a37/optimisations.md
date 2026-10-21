### Prev: expt_a17

The final design, `expt_a17`, with 1 shard(s) per distributed table instead
of 4 (`CITUS_SHARD_COUNT` defaults to 1). Nothing else changes. Part of the
shard-count study around the final design, as `expt_b42` to `expt_b46` are
for workload B (1, 2, 8, 16 and 32 shards); `expt_a18` and `expt_a19`,
replicates of `expt_a17` in the same batch, are the 4-shard reference.

Run: job 979119, team id 304, on `xcnf[0-2,4,5]`, in the same batch as `expt_a18` and `expt_a19` (jobs 979011, 979012).

Result: killed by Slurm OOM handling during the 1-client run (xcnf1, the only worker
holding data, exceeded the job step memory limit); that point is invalid and no
other client count ran.
