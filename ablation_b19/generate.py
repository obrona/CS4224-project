"""Build the workload-B ablation and shard-count sweep around expt_b19:
expt_b27 .. expt_b46.

Run from anywhere:
    python3 ablation_b19/generate.py           # write the 20 cells and manifest.csv
    python3 ablation_b19/generate.py --check   # verify what is on disk, exit 1 on failure

expt_b19 is the final design (SERIALIZABLE, 4 shards, delegated T1, T7 reading
one merged lookup from the reference table product_merchant_map). Four factors
are switched on or off around it:

    T5R  T5 routing     on: expt_b19's T5 + order_merchant_map, written by T1
                        off: expt_b8's T5 (UPDATE sent to every orders shard)
    T6R  T6 rollup      on: expt_b19's T6 + merchant_daily_sales, upserted by T1
                        off: expt_b8's T6 (scans orders)
    T7R  T7 routing     on: expt_b19's T7 + product_merchant_map (reference table,
                            coordinator registered in Citus's metadata)
                        off: expt_b8's T7 (six statements to every inventory shard)
    DEL  T1 delegated   on: expt_b19's place_order, with step 6 (rollup upsert)
                            and/or step 7 (map insert) removed when T6R/T5R is off
                        off: expt_b8's multi-statement T1 in BEGIN/COMMIT, with the
                            map insert and/or rollup upsert added before COMMIT

Everything else is expt_b19's. An "off" factor removes everything it added to
run.sh (table, index, distribution, data load, TRUNCATE entry), so run.sh only
ever loses lines relative to expt_b19's, apart from the TRUNCATE line.

Cells: expt_b27 .. expt_b41 are the other 15 cells of the 2^4 grid, numbered in
submission priority: one factor off (b27-b30), two off (b31-b36), three off
(b37-b40), all off (b41). expt_b19 itself is the all-on cell, and expt_b20 and
expt_b21 already replicate it. expt_b42 .. expt_b46 are expt_b19 with 1, 2, 8,
16 and 32 shards per distributed table instead of 4; nothing else changes.
"""

import argparse
import itertools
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "ablation_b19"
SOURCES = HERE / "sources"
BASE = ROOT / "expt_b19"      # final design, the all-on cell
OLD = ROOT / "expt_b8"        # source of every "off" transaction

FACTORS = ["T5R", "T6R", "T7R", "DEL"]
FACTOR_DESC = {
    "T5R": "T5 routing",
    "T6R": "T6 rollup",
    "T7R": "T7 routing",
    "DEL": "T1 delegated",
}
TX = {
    "T5R": "T5_update_order_status",
    "T6R": "T6_global_sales",
    "T7R": "T7_inventory_transfer",
}
TX_NAMES = [
    "T1_place_order", "T2_update_inventory", "T3_order_history",
    "T4_product_lookup", "T5_update_order_status", "T6_global_sales",
    "T7_inventory_transfer", "T8_update_customer", "T9_update_product",
]
REPLICATES = ["expt_b20", "expt_b21"]   # already run; listed in the manifest only
FIRST_CELL = 27
BASE_SHARDS = 4
SHARD_LINE = 'CITUS_SHARD_COUNT="${{CITUS_SHARD_COUNT:-{}}}"'
SHARD_CELLS = [("expt_b42", 1), ("expt_b43", 2), ("expt_b44", 8),
               ("expt_b45", 16), ("expt_b46", 32)]


def cells():
    """(name, set of factors switched off), in submission priority."""
    out, n = [], FIRST_CELL
    for k in range(1, len(FACTORS) + 1):
        for off in itertools.combinations(FACTORS, k):
            out.append((f"expt_b{n}", set(off)))
            n += 1
    return out


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


# --------------------------------------------------------------------- run.sh

def remove_block(lines, where, start, end, before=0, blank_before=False, blank_after=False):
    """Delete from the unique line equal to `start` (optionally extended
    `before` lines up) to the first line at or after it containing `end`;
    end "SQL" must be the whole line (a heredoc terminator)."""
    hits = [i for i, l in enumerate(lines) if l.rstrip() == start.rstrip()]
    if len(hits) != 1:
        raise ValueError(f"{where}: {start!r} found {len(hits)} times")
    i = hits[0] - before

    def ends(line):
        return line.strip() == end if end == "SQL" else end in line

    j = next((k for k in range(hits[0], len(lines)) if ends(lines[k])), None)
    if j is None:
        raise ValueError(f"{where}: no {end!r} after {start!r}")
    if blank_before:
        if lines[i - 1].strip():
            raise ValueError(f"{where}: no blank line before {start!r}")
        i -= 1
    if blank_after:
        if lines[j + 1].strip():
            raise ValueError(f"{where}: no blank line after block ending {end!r}")
        j += 1
    del lines[i:j + 1]


def edit_truncate(lines, table, where):
    hits = [i for i, l in enumerate(lines) if "psqlx -c \"TRUNCATE TABLE " in l]
    if len(hits) != 1:
        raise ValueError(f"{where}: TRUNCATE line found {len(hits)} times")
    i = hits[0]
    if lines[i].count(f"{table},") != 1:
        raise ValueError(f"{where}: {table} not in the TRUNCATE list once")
    lines[i] = lines[i].replace(f"{table},", "", 1)


def drop_table_line(lines, table, where):
    remove_block(lines, where, f"DROP TABLE IF EXISTS {table} CASCADE;", ";")


def run_sh(off):
    where = "run.sh"
    lines = read(BASE / "run.sh").split("\n")
    if "T7R" in off:
        remove_block(lines, where,
                     "# Register the coordinator in Citus's metadata, so it holds its own copy of",
                     "citus_set_coordinator_host", blank_after=True)
        drop_table_line(lines, "product_merchant_map", where)
        remove_block(lines, where,
                     "-- Routing table for T7, which is given only product ids. A reference table",
                     ");", blank_after=True)
        remove_block(lines, where,
                     "\t\tIF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'product_merchant_map'::regclass) THEN",
                     "END IF;", blank_before=True)
        remove_block(lines, where,
                     "\t# No transaction inserts products or changes a product's merchant,",
                     "SQL", blank_after=True)
        edit_truncate(lines, "product_merchant_map", where)
    if "T5R" in off:
        drop_table_line(lines, "order_merchant_map", where)
        remove_block(lines, where,
                     "-- Routing table for T5, which is given only an order id. Sharded by order_id,",
                     ");", blank_after=True)
        remove_block(lines, where,
                     "\t\tIF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'order_merchant_map'::regclass) THEN",
                     "END IF;", blank_before=True)
        remove_block(lines, where,
                     "INSERT INTO order_merchant_map (order_id, merchant_id)",
                     "SQL", before=1, blank_after=True)
        edit_truncate(lines, "order_merchant_map", where)
    if "T6R" in off:
        drop_table_line(lines, "merchant_daily_sales", where)
        remove_block(lines, where,
                     "-- Per-merchant, per-day revenue rollup for T6. Distributed by merchant_id and",
                     ");", blank_after=True)
        remove_block(lines, where,
                     "CREATE INDEX IF NOT EXISTS idx_mds_period",
                     "INCLUDE (merchant_id, order_count, revenue);", blank_before=True)
        remove_block(lines, where,
                     "\t\tIF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'merchant_daily_sales'::regclass) THEN",
                     "END IF;", blank_before=True)
        remove_block(lines, where,
                     "INSERT INTO merchant_daily_sales (merchant_id, sales_date, order_count, revenue)",
                     "SQL", before=1, blank_after=True)
        edit_truncate(lines, "merchant_daily_sales", where)
    if "DEL" in off:
        remove_block(lines, where,
                     "\t# T1 runs as one distributed function, delegated to its merchant's worker.",
                     'psqlx <<<"$t1_function"', blank_before=True)
    return "\n".join(lines)


# ---------------------------------------------------------------- transactions

# First line of each removable step of place_order; a step runs to the next
# blank line inclusive (the same rule as ablation/generate.py on main).
FN_STEP_HEAD = {
    "T6R": "  -- 6. Keep the T6 rollup in step.",
    "T5R": "  -- 7. order_merchant_map is sharded by order_id, so this row usually lives",
}

ORIGINAL_COMMIT = """\
UPDATE orders
SET total_amount = (:order_total)::numeric(12,2)
WHERE merchant_id = (:merchant_id)::bigint
  AND order_id = (:new_order_id)::bigint;
COMMIT;"""

ORIGINAL_MAP = """
-- Keep order_merchant_map in step with orders, for T5's routed lookup.
INSERT INTO order_merchant_map (order_id, merchant_id)
VALUES ((:new_order_id)::bigint, (:merchant_id)::bigint);"""

ORIGINAL_ROLLUP = """
-- Keep the T6 rollup in step with orders. It runs last before COMMIT, so the
-- merchant's row for today stays locked as briefly as possible. The order's
-- created_at is this transaction's CURRENT_TIMESTAMP, so CURRENT_TIMESTAMP::date
-- is its day, and the revenue is the same total just written to orders.
INSERT INTO merchant_daily_sales AS s (merchant_id, sales_date, order_count, revenue)
VALUES ((:merchant_id)::bigint, CURRENT_TIMESTAMP::date, 1, (:order_total)::numeric(12,2))
ON CONFLICT (merchant_id, sales_date)
DO UPDATE SET order_count = s.order_count + 1,
              revenue     = s.revenue + EXCLUDED.revenue;"""


def t1_delegated(off):
    lines = read(BASE / "transactions" / "T1_place_order.sql").split("\n")
    for f in ("T6R", "T5R"):
        if f not in off:
            continue
        hits = [i for i, l in enumerate(lines) if l == FN_STEP_HEAD[f]]
        if len(hits) != 1:
            raise ValueError(f"place_order: step head for {f} found {len(hits)} times")
        start = hits[0]
        stop = lines.index("", start)
        del lines[start:stop + 1]
    return "\n".join(lines)


def t1_original(off):
    text = read(OLD / "transactions" / "T1_place_order.sql")
    if text.count(ORIGINAL_COMMIT) != 1:
        raise ValueError("expt_b8 T1: final UPDATE ... COMMIT block not found once")
    extra = ""
    if "T5R" not in off:
        extra += ORIGINAL_MAP + "\n"
    if "T6R" not in off:
        extra += ORIGINAL_ROLLUP + "\n"
    if extra:
        head = ORIGINAL_COMMIT[: -len("COMMIT;")]
        text = text.replace(ORIGINAL_COMMIT, head + extra + "COMMIT;", 1)
    return text


def t1_original_explain(off):
    text = read(SOURCES / "explain" / "T1_original.sql")
    if "T5R" not in off:
        text += read(SOURCES / "explain" / "T1_original_map.sql")
    if "T6R" not in off:
        text += read(SOURCES / "explain" / "T1_original_rollup.sql")
    return text + "\nROLLBACK;\n"


def cell_files(off):
    """relative path -> text for one cell."""
    files = {"run.sh": run_sh(off)}
    for tx in TX_NAMES:
        base_tx = read(BASE / "transactions" / f"{tx}.sql")
        base_ex = read(BASE / "explain" / f"{tx}.sql")
        if tx == "T1_place_order":
            if "DEL" in off:
                files[f"transactions/{tx}.sql"] = t1_original(off)
                files[f"explain/{tx}.sql"] = t1_original_explain(off)
            else:
                files[f"transactions/{tx}.sql"] = t1_delegated(off)
                files[f"explain/{tx}.sql"] = base_ex  # every delegated cell makes the same call
            continue
        factor = next((f for f, t in TX.items() if t == tx), None)
        if factor in off:
            files[f"transactions/{tx}.sql"] = read(OLD / "transactions" / f"{tx}.sql")
            files[f"explain/{tx}.sql"] = read(SOURCES / "explain" / f"{tx}_off.sql")
        else:
            files[f"transactions/{tx}.sql"] = base_tx
            files[f"explain/{tx}.sql"] = base_ex
    return files


def shard_run_sh(shards):
    text = read(BASE / "run.sh")
    old = SHARD_LINE.format(BASE_SHARDS)
    if text.count(old) != 1:
        raise ValueError(f"run.sh: {old!r} not found once")
    return text.replace(old, SHARD_LINE.format(shards), 1)


def shard_files(shards):
    files = {"run.sh": shard_run_sh(shards)}
    for tx in TX_NAMES:
        files[f"transactions/{tx}.sql"] = read(BASE / "transactions" / f"{tx}.sql")
        files[f"explain/{tx}.sql"] = read(BASE / "explain" / f"{tx}.sql")
    return files


# ------------------------------------------------------------- documentation

OFF_TEXT = {
    "T5R": ("T5 is `expt_b8`'s: one `UPDATE orders` by `order_id`, sent to every "
            "`orders` shard. There is no `order_merchant_map`: `run.sh` does not "
            "create, distribute, fill or truncate it, and T1 does not write it."),
    "T6R": ("T6 is `expt_b8`'s: it aggregates the 30-day window from `orders`. "
            "There is no `merchant_daily_sales` or `idx_mds_period`: `run.sh` does "
            "not create, distribute, fill or truncate them, and T1 does not upsert "
            "the rollup."),
    "T7R": ("T7 is `expt_b8`'s: six statements by `product_id`/`inventory_id`, each "
            "sent to every `inventory` shard. There is no `product_merchant_map`, and "
            "the coordinator is not registered in Citus's metadata (it was only "
            "needed for that reference table)."),
    "DEL": ("T1 is `expt_b8`'s multi-statement T1 inside `BEGIN`/`COMMIT`, sent "
            "statement by statement through the coordinator; each item's inventory "
            "`UPDATE` keeps its own `quantity >= qty` guard. `run.sh` does not "
            "create `place_order`."),
}
ON_T1_EXTRA = {
    "T5R": "the `order_merchant_map` insert",
    "T6R": "the `merchant_daily_sales` upsert (for `CURRENT_TIMESTAMP::date`, the order's day)",
}
PROSE = {"T5R": "T5 routing", "T6R": "the T6 rollup", "T7R": "T7 routing", "DEL": "T1 delegation"}
FN_STEP = {"T5R": 7, "T6R": 6}


def and_list(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def optimisations_md(name, off):
    on = [f for f in FACTORS if f not in off]
    lines = [
        "### Prev: expt_b19",
        "",
        f"Cell of the 2^4 ablation around `expt_b19` (`ablation_b19/README.md`): "
        f"`expt_b19` with {and_list([PROSE[f] for f in FACTORS if f in off])} "
        f"switched off. Everything else is `expt_b19`'s, including `SERIALIZABLE` "
        f"and 4 shards. Generated by `ablation_b19/generate.py`; do not edit by hand.",
        "",
        "| Factor | Level |",
        "| ------ | ----- |",
    ]
    for f in FACTORS:
        level = "off" if f in off else "on"
        if f == "DEL":
            level = "off (`expt_b8`'s T1)" if f in off else "on (`place_order`)"
        lines.append(f"| {FACTOR_DESC[f]} | {level} |")
    lines += ["", "### What is switched off", ""]
    for f in FACTORS:
        if f in off:
            lines += [f"- **{FACTOR_DESC[f]}.** {OFF_TEXT[f]}"]
    if "DEL" in off:
        kept = [f for f in ("T5R", "T6R") if f in on]
        if kept:
            one = len(kept) == 1
            steps = and_list([str(FN_STEP[f]) for f in kept])
            lines += [
                "",
                "Because " + and_list([PROSE[f] for f in kept])
                + (" is" if one else " are") + " on, the original T1 also runs "
                + " and then ".join(ON_T1_EXTRA[f] for f in kept)
                + ", after its final `UPDATE orders SET total_amount` and before "
                "`COMMIT`, using the same `(:order_total)::numeric(12,2)`. The original "
                "T1 never ran with " + ("this write" if one else "these writes")
                + " in the chain; " + ("it mirrors step " if one else "they mirror steps ")
                + steps + " of `place_order`.",
            ]
    else:
        removed = [s for f, s in (("T6R", "6 (rollup upsert)"), ("T5R", "7 (map insert)")) if f in off]
        if removed:
            lines += [
                "",
                "T1 is `expt_b19`'s `place_order` with step"
                + ("s " if len(removed) > 1 else " ") + " and ".join(removed)
                + " removed from the function body; nothing else in the file changes.",
            ]
    lines += [
        "",
        "### What to look at when this is run",
        "",
        "- **Comparability.** Same nodes as `expt_b19` (`xcnf[17-21]`), run alone: "
        "`ablation_b19/submit.sh` chains every cell with `afterany`.",
        "- **`schema-create.log` and `explain.log`.** No errors; switched-off tables "
        "are absent.",
        "- **`pgbench_exit_code`, aborted clients, retries and serialization failures** "
        "at every client count.",
        "",
    ]
    return "\n".join(lines)


SHARD_LAYOUT = {
    1: ("Every merchant-colocated table is a single shard, so they all sit on one "
        "worker: that worker runs every merchant-scoped transaction, and T6 is one "
        "task. The other three workers hold none of those tables."),
    2: ("The merchant-colocated tables have 2 shards, so they sit on two of the "
        "four workers and the other two hold none of them. T6 runs 2 tasks."),
    8: "2 shards per worker; T6 runs 8 tasks, as in `expt_b14`.",
    16: "4 shards per worker; T6 runs 16 tasks.",
    32: "8 shards per worker, Citus's default; T6 runs 32 tasks, as in `expt_b13`.",
}


def shard_md(name, shards):
    return "\n".join([
        "### Prev: expt_b19",
        "",
        f"Shard-count cell around `expt_b19` (`ablation_b19/README.md`): `expt_b19` "
        f"with `CITUS_SHARD_COUNT` {shards} instead of {BASE_SHARDS}. `run.sh` differs "
        f"from `expt_b19`'s only in that default, and `transactions/` and `explain/` "
        f"are identical. Generated by `ablation_b19/generate.py`; do not edit by hand.",
        "",
        "### What this tests",
        "",
        "`expt_b13` (32 shards), `expt_b14` (8) and `expt_b15` (4) swept the shard "
        "count before T7 was routed through the reference table (`expt_b17` .. "
        "`expt_b19`). `expt_b42` .. `expt_b46` repeat the sweep on the final design, "
        "with 1 and 2 shards added. The shard count applies to every distributed "
        "table, including `order_merchant_map`.",
        "",
        f"- **{shards} shard{'s' if shards > 1 else ''}.** {SHARD_LAYOUT[shards]}",
        "",
        "### What to look at when this is run",
        "",
        "- **Comparability.** Same nodes as `expt_b19` (`xcnf[17-21]`), run alone: "
        "`ablation_b19/submit.sh` chains every cell with `afterany`.",
        "- **`topology.txt` and `explain.log`.** Which workers hold shards, and T6's "
        "task count.",
        "- **`pgbench_exit_code`, aborted clients, retries and serialization failures** "
        "at every client count.",
        "",
    ])


def manifest():
    rows = ["experiment,t5_routing,t6_rollup,t7_routing,t1_delegated,shard_count,source"]
    rows.append(f"expt_b19,1,1,1,1,{BASE_SHARDS},final design")
    for r in REPLICATES:
        rows.append(f"{r},1,1,1,1,{BASE_SHARDS},replicate of expt_b19")
    for name, off in cells():
        rows.append(name + "," + ",".join("0" if f in off else "1" for f in FACTORS)
                    + f",{BASE_SHARDS},generated")
    for name, shards in SHARD_CELLS:
        rows.append(f"{name},1,1,1,1,{shards},generated")
    return "\n".join(rows) + "\n"


# ------------------------------------------------------------------- driver

def all_outputs():
    """directory -> {relative path -> text}"""
    out = {}
    for name, off in cells():
        files = cell_files(off)
        files["optimisations.md"] = optimisations_md(name, off)
        out[name] = files
    for name, shards in SHARD_CELLS:
        files = shard_files(shards)
        files["optimisations.md"] = shard_md(name, shards)
        out[name] = files
    return out


def write(outputs):
    for d, files in outputs.items():
        target = ROOT / d
        if (target / "slurm-results").exists():
            raise SystemExit(f"{d} already has slurm-results/; refusing to overwrite its code")
        if target.exists():
            shutil.rmtree(target)
        for rel, text in files.items():
            p = target / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="\n")
    (HERE / "manifest.csv").write_text(manifest(), encoding="utf-8", newline="\n")
    print(f"wrote {len(outputs)} cells and ablation_b19/manifest.csv")


def check(outputs):
    errors = []
    base_run = read(BASE / "run.sh").split("\n")
    for d, files in outputs.items():
        target = ROOT / d
        for rel, text in files.items():
            p = target / rel
            if rel == "optimisations.md" and (target / "slurm-results").exists():
                continue
            if not p.exists() or read(p) != text:
                errors.append(f"{d}/{rel} differs from the generator's output")
        on_disk = {str(p.relative_to(target)).replace("\\", "/") for p in target.rglob("*")
                   if p.is_file() and "slurm-results" not in p.parts and not p.name.startswith("citus-")}
        extra = on_disk - set(files)
        if extra:
            errors.append(f"{d}: unexpected files {sorted(extra)}")
        # run.sh only loses lines relative to expt_b19's, apart from the TRUNCATE
        # line (ablation cells) or the shard-count default (shard cells).
        run = [l for l in files["run.sh"].split("\n")
               if "TRUNCATE TABLE" not in l and not l.startswith("CITUS_SHARD_COUNT=")]
        it = iter(base_run)
        if not all(any(l == b for b in it) for l in run):
            errors.append(f"{d}/run.sh is not expt_b19's run.sh with lines removed")
    for name, off in cells():
        files = outputs[name]
        run = files["run.sh"]
        for f, table in (("T5R", "order_merchant_map"), ("T6R", "merchant_daily_sales"),
                         ("T7R", "product_merchant_map")):
            if (table in run) == (f in off):
                errors.append(f"{name}: {table} {'present' if f in off else 'missing'} in run.sh")
        t1 = files["transactions/T1_place_order.sql"]
        if ("\\if 0" in t1) == ("DEL" in off) or ("t1_function" in run) == ("DEL" in off):
            errors.append(f"{name}: T1 / place_order creation does not match DEL")
        for f, table in (("T5R", "order_merchant_map"), ("T6R", "merchant_daily_sales")):
            if (table in t1) == (f in off):
                errors.append(f"{name}: T1 {'writes' if f in off else 'does not write'} {table}")
    base_text = read(BASE / "run.sh")
    for name, shards in SHARD_CELLS:
        diff = [(a, b) for a, b in zip(base_text.split("\n"), outputs[name]["run.sh"].split("\n")) if a != b]
        if diff != [(SHARD_LINE.format(BASE_SHARDS), SHARD_LINE.format(shards))]:
            errors.append(f"{name}/run.sh differs from expt_b19's in more than the shard count")
        for tx in TX_NAMES:
            for sub in ("transactions", "explain"):
                if outputs[name][f"{sub}/{tx}.sql"] != read(BASE / sub / f"{tx}.sql"):
                    errors.append(f"{name}/{sub}/{tx}.sql differs from expt_b19's")
    m = HERE / "manifest.csv"
    if not m.exists() or read(m) != manifest():
        errors.append("ablation_b19/manifest.csv differs from the generator's output")
    for e in errors:
        print("FAIL", e)
    print("check:", "OK" if not errors else f"{len(errors)} failure(s)",
          f"({len(outputs)} cells)")
    return not errors


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="verify the cells on disk")
    args = ap.parse_args()
    outputs = all_outputs()
    if args.check:
        sys.exit(0 if check(outputs) else 1)
    write(outputs)


if __name__ == "__main__":
    main()
