### Prev: expt_a15

T7's two product-to-merchant lookups are merged into one statement;
`product_merchant_map` stays a distributed table sharded by `product_id`, as
in `expt_a15`. This is the same change as `expt_b18`, and the transactions
are identical to `expt_b18`'s.

Run: job 927067, team id 304, on `xcnf[0-2,4,5]`, at the same time as the other
five of `expt_a15` to `expt_a20` on the same nodes (team ids 4 to 504, one per
experiment).
