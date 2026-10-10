### Prev: expt_a15

`product_merchant_map`, T7's product-to-merchant lookup table, becomes a
reference table, and the coordinator is registered in Citus's metadata so that
it holds a copy; T7's two lookups then read the coordinator's local copy
instead of going to a worker. T7's transfer is `expt_a15`'s. This is the same
change as `expt_b17`, and the transactions are identical to `expt_b17`'s.

Run: job 927066, team id 204, on `xcnf[0-2,4,5]`, at the same time as the other
five of `expt_a15` to `expt_a20` on the same nodes (team ids 4 to 504, one per
experiment).
