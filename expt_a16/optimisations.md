### Prev: expt_a15

T7's debit and credit move into a distributed function, `transfer_inventory`,
delegated to the worker that holds the source merchant's shard; the two
product-to-merchant lookups stay as they were. This step is not carried
forward: `expt_a17` to `expt_a19` build on `expt_a15`. This is the same
change as `expt_b16`, and the transactions are identical to `expt_b16`'s.

Run: job 927065, team id 104, on `xcnf[0-2,4,5]`, at the same time as the other
five of `expt_a15` to `expt_a20` on the same nodes (team ids 4 to 504, one per
experiment).
