### Prev: expt_a15

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

Run: job 972057, team id 404, on `xcnf[0-2,4,5]`, at the same time as the other five jobs of this batch (972053 to 972058).
