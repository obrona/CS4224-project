Benchmark metrics
=================

summary.csv
  One row per client count. Includes:
  - overall average latency (ms)
  - overall median / p50 latency (ms)
  - overall p95 and p99 latency (ms)
  - successful transaction count
  - overall TPS
  - number of transactions that had to retried at least once
  - total number of transaction retries 
  - number of serialization failures
  - number of deadlock failures
  - pgbench exit code

transaction_metrics.csv
  One row per client count and transaction type (T1-T9). Includes:
  - average latency (ms)
  - p50 latency (ms)
  - p95 latency (ms)
  - p99 latency (ms)
  - successful transaction count
  - per-transaction TPS

logs/
  Raw pgbench per-transaction logs and one combined transaction log per client count.

metrics-cN/
  Extracted latency samples in microseconds for the overall workload and each
  transaction type.

Notes:
  Latency metrics are computed from pgbench's per-transaction log records.
  LOG_SAMPLE_RATE=1.0. For complete latency distributions, leave
  LOG_SAMPLE_RATE=1.0.
