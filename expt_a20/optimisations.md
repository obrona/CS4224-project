### Prev: expt_a15

(Run and logged as `expt_a18`; renamed `expt_a20` when the replicates of `expt_a17` took the numbers `expt_a18` and `expt_a19`.)

Each merchant-day row of `merchant_daily_sales` is split into 4 slots: the
table gets `slot SMALLINT NOT NULL` and primary key
`(merchant_id, sales_date, slot)`, the initial fill groups by
`order_id % 4`, and `place_order` step 6 upserts slot
`(p_order_id % 4)::smallint`. T6 is unchanged: it already sums
`order_count` and `revenue` over all rows per merchant, so its results are
identical.

Expected to remove: most write-write conflicts on the hot rollup row. Every
T1 for a merchant on a given day upserts the same row, so concurrent orders
for a hot merchant queue on that row's lock and, under serializable
isolation, the later writer can abort with a serialization failure; with 4
slots, two concurrent orders hit the same row about a quarter of the time.

Run: job 972057, team id 404, on `xcnf[0-2,4,5]`, in the same batch as `expt_a16`, `expt_a17`, `expt_a20` and `expt_a21` (jobs 972055 to 972058).
