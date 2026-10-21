### Prev: expt_a15

(Run and logged as `expt_a19`; renamed `expt_a21`, see `expt_a20`.)

Both `expt_a17`'s and `expt_a20`'s changes on `expt_a15`, and nothing else:
order ids chosen by `public.next_colocated_order_id` so the
`order_merchant_map` row (now colocated with `merchants`) lands on the
merchant's worker, and `merchant_daily_sales` split into 4 slots by
`order_id % 4`.

Expected to remove: the two-phase commit on every T1 (`expt_a17`) and most
write-write conflicts on the hot rollup row (`expt_a20`). Note the slot is
`order_id % 4` and the order id is now chosen by shard placement; the two are
not correlated through Citus's hash, so slots should still spread evenly, but
this is not checked.

Run: job 972058, team id 504, on `xcnf[0-2,4,5]`, in the same batch as `expt_a16`, `expt_a17`, `expt_a20` and `expt_a21` (jobs 972055 to 972058).
