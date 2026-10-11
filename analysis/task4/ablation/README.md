# Archived: 2^4 ablation around the REPEATABLE READ design

These CSVs summarise the first ablation, `expt_b21` .. `expt_b37`: a 2^4
factorial (T5 routing, T6 rollup, T7 routing, T1 delegation) around the
`REPEATABLE READ` design, now `expt_b26`, with two replicates. All 17 runs
completed on 2026-10-09/10 (jobs 925400 .. 925416). On 2026-10-11 the folders
were deleted so that the numbers could be reused for an ablation around the
`SERIALIZABLE` final design `expt_b19`. The runs remain in git: commits
`41928f59` .. `59822755`, for example `git checkout 59822755 -- expt_b23`.

`collect_ablation.py` built these files from those folders and no longer runs
as is. Its numbers are kept for the record and for comparison with the new
ablation. `cells.csv` and `manifest.csv` use the old cell names; in them,
`expt_b20` is the `REPEATABLE READ` design (now `expt_b26`).

## The midnight artefact

`midnight.csv` lists every client-count run, in any experiment, whose data was
reset before midnight and measured after it. Three runs did: `expt_b13` at 8
clients, `expt_b17` at 8 clients (from 3 min 46 s into the run), and the old
`expt_b22` at 64 clients.

Each reset regenerates `orders` with `created_at = current_timestamp - k days`
(k = 0 .. 364, `run.sh` line 644), so every initial order carries the clock
time of the reset, about 13,700 orders per day. From `expt_b12` on, T6 reads
the oldest day of its 30-day window (from `now - 30 days` to that day's
midnight) live from `orders`, and every later day from the rollup
`merchant_daily_sales`. In the same calendar day as the reset, the current
clock time is later than the reset's, so the live part starts after that day's
orders and is empty. After midnight it starts just after 00:00 and contains the
whole day's orders. T6's answer covers the same 30 days either way, but one day
moves from about 1,000 rollup rows to about 13,700 orders scanned and
aggregated.

`expt_b17` at 8 clients shows the effect within one run: 2,625 TPS with T6 at
6.8 ms before midnight, 2,317 TPS with T6 at 9.8 ms after it, while T1, T2 and
T7 barely change. The old `expt_b22` at 64 clients ran wholly after midnight,
13.6% below its twin `expt_b21`; its T6 and T1 also slowed steadily during the
run (T6 31.6 -> 49.9 ms per 60 s window), which the extra scan does not explain.
The baseline T6 (before `expt_b12`) scans all 30 days from `orders` and is not
affected.

## Findings worth keeping

- **Noise.** Same-night replicates agreed within 1.1% at every client count
  (excluding the midnight run); `expt_b20` (then the design itself), run 11 days
  earlier, differed by up to 5.5%.
- **Leave-one-out against the chain** (mean TPS): T7 routing 5.46x (chain step
  1.59x), T6 rollup 5.13x (3.01x), T1 delegation 1.28x (1.11x), T5 routing 1.17x
  (1.07x).
- **Hierarchy.** With T7 routing off, T7 holds 61-63 of 64 clients in every
  cell. With T7 on and the rollup off, T6 holds 51-55. The rollup and T7
  routing are each worth 3.5-5.5x with the other on and 1.7-2.0x without it.
  T5 routing and T1 delegation help only when both are on.
- **T5 routing is a trade-off.** Without it, throughput is 13% higher at 1
  client and 8% at 8, and T1 takes 4.9 ms instead of about 10.3 ms at 1 client
  (no write to `order_merchant_map` on a second worker); routing wins at 4 and
  from 16 clients, by up to 37% at 64. Retried transactions at 8 clients: 322
  without it, about 1,000 with it.
