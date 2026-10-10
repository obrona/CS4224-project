### Prev: expt_a14

Every distributed table is created with 4 shards, one per worker, instead of
`expt_a14`'s 8 (`CITUS_SHARD_COUNT` defaults to 4), so T6 runs one task per
worker. Nothing else changes. This is the same change as `expt_b15`, and the
transactions are identical to `expt_b15`'s.

Run: job 927064, team id 4, on `xcnf[0-2,4,5]`, at the same time as the other
five of `expt_a15` to `expt_a20` on the same nodes (team ids 4 to 504, one per
experiment).
