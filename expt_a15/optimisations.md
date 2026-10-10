### Prev: expt_a14

Every distributed table is created with 4 shards, one per worker, instead of
`expt_a14`'s 8 (`CITUS_SHARD_COUNT` defaults to 4), so T6 runs one task per
worker. Nothing else changes. This is the same change as `expt_b15`, and the
transactions are identical to `expt_b15`'s.

Run: job 927064, team id 4, on `xcnf[0-2,4,5]`, at the same time as five other
jobs on the same nodes (team ids 104 to 504), runs of T7 and isolation steps
that were dropped from the chain; they are in git history at `20642f40`.
