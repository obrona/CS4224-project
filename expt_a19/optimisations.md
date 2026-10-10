### Prev: expt_a15

Combines `expt_a17` and `expt_a18`: `product_merchant_map` is a reference
table with the coordinator registered in Citus's metadata, and T7 makes its
two lookups in one merged statement, so it does one local lookup on the
coordinator. This is the same change as `expt_b19`, and the transactions are
identical to `expt_b19`'s.

Run: job 927068, team id 404, on `xcnf[0-2,4,5]`, at the same time as the other
five of `expt_a15` to `expt_a20` on the same nodes (team ids 4 to 504, one per
experiment).
