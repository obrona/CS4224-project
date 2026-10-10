### Prev: expt_a19

The isolation level on every node is lowered from `SERIALIZABLE` to
`REPEATABLE READ` (`PG_ISOLATION_LEVEL` in `run.sh`, written to each node's
`default_transaction_isolation`), which still detects write-write conflicts.
Nothing else changes. This is the same change as `expt_b20`, and the
transactions are identical to `expt_b20`'s.

Run: job 927069, team id 504, on `xcnf[0-2,4,5]`, at the same time as the other
five of `expt_a15` to `expt_a20` on the same nodes (team ids 4 to 504, one per
experiment).
