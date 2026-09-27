A7 transaction plans and execution
==================================
T1.txt contains EXPLAIN without ANALYZE and a psql Time line from executing
T1 once. Citus does not support EXPLAIN ANALYZE for its coordinator-side
INSERT ... SELECT. T2.txt through T9.txt contain EXPLAIN ANALYZE output.
sql/T1.sql through sql/T9.sql contain the exact SQL executed.
status.csv records success or failure for every transaction.
Each transaction runs once with representative existing IDs against the A7
synthetic dataset (scale=1, seed=42). Changes are rolled back
between transactions. T5 uses the SHIPPED branch; T7 uses product IDs 1 and 2.
EXPLAIN ANALYZE executes writes; T1 is also executed after EXPLAIN.
T1 sequence values advance despite rollback.
