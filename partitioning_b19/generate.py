"""Build the alternative-partitioning experiments around expt_b19: expt_b22 .. expt_b25.

Run from anywhere:
    python3 partitioning_b19/generate.py           # write the four cells
    python3 partitioning_b19/generate.py --check   # verify what is on disk, exit 1 on failure

Each cell is expt_b19 (the final design) with one table placement changed:

    expt_b22  products + inventory distributed by product_id (one colocation group)
    expt_b23  orders + order_items distributed by order_id (one colocation group)
    expt_b24  products + inventory as single-shard tables, colocated: one node
    expt_b25  inventory as a reference table (a copy on every node)

Everything else is expt_b19's. The changes each placement forces are applied
with it and listed in the cell's optimisations.md: keys that must contain the
new distribution column, the lookup table the placement makes unnecessary, and
the T1/T5/T7 that fit it. The helpers that remove a lookup table or swap T1
are ablation_b20/generate.py's, so these cells and the ablation cells are built
the same way.
"""

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "partitioning_b19"
SOURCES = HERE / "sources"

sys.dont_write_bytecode = True  # no __pycache__ in ablation_b20/
_spec = importlib.util.spec_from_file_location("ablation_b20_generate",
                                               ROOT / "ablation_b20" / "generate.py")
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)

# The final design is expt_b19 (SERIALIZABLE). ablation_b20's helpers read their
# base from its module-level BASE at call time, so point it at expt_b19.
ab.BASE = ROOT / "expt_b19"
BASE, OLD, read = ab.BASE, ab.OLD, ab.read
TX_NAMES = ab.TX_NAMES

CELLS = ["expt_b22", "expt_b23", "expt_b24", "expt_b25"]


def replace_once(text, old, new, where):
    if text.count(old) != 1:
        raise ValueError(f"{where}: {old.splitlines()[0]!r}... found {text.count(old)} times")
    return text.replace(old, new, 1)


INV_KEYS = ("\tPRIMARY KEY (merchant_id, inventory_id),\n\tUNIQUE (merchant_id, product_id)",
            "\tPRIMARY KEY (product_id, inventory_id),\n\tUNIQUE (product_id, merchant_id)")
ITEM_KEY = ("\tPRIMARY KEY (merchant_id, order_item_id)",
            "\tPRIMARY KEY (order_id, order_item_id)")


def dist(table, column, colocate):
    col = "NULL" if column is None else f"'{column}'"
    return f"PERFORM create_distributed_table('{table}', {col}, colocate_with => '{colocate}');"


def merchant_dist(table):
    return dist(table, "merchant_id", "merchants")


ITEMS_LOAD = ("SELECT y.order_item_id,y.merchant_id,y.order_id,y.product_id,y.qty,p.price\n"
              "FROM y\n"
              "JOIN products p\n"
              "  ON p.merchant_id=y.merchant_id\n"
              " AND p.product_id=y.product_id;",
              "-- unit_price is products.price as generated above, by the same formula, so\n"
              "-- this load needs no join with products, which this layout does not\n"
              "-- colocate with orders. Every y row has exactly one product.\n"
              "SELECT y.order_item_id,y.merchant_id,y.order_id,y.product_id,y.qty,"
              "(1+(((y.product_id::bigint * 7919))%100000)/100.0)::numeric(12,2)\n"
              "FROM y;")

INV_LOAD = ("INSERT INTO inventory SELECT product_id,merchant_id,product_id,10+((hashint8extended(product_id,$DATA_SEED)&9223372036854775807)%991)::int,current_timestamp FROM products;",
            "-- Generated directly instead of INSERT ... SELECT FROM products: Citus 14.1.0\n"
            "-- pushes that statement down between the two single-shard tables with an\n"
            "-- empty distribution-column filter, WHERE ( IS NOT NULL), which the worker\n"
            "-- rejects (job 930969). Same rows: one per product, with its merchant.\n"
            "INSERT INTO inventory SELECT i,1+((i::bigint - 1)%$NUM_MERCHANTS),i,"
            "10+((hashint8extended(i,$DATA_SEED)&9223372036854775807)%991)::int,current_timestamp "
            "FROM generate_series(1::bigint, $NUM_PRODUCTS::bigint) g(i);")

COORD_COMMENT = ("# Register the coordinator in Citus's metadata, so it holds its own copy of\n"
                 "# reference table and reads product_merchant_map locally. It gets no\n",
                 "# Register the coordinator in Citus's metadata, so it holds its own copy of\n"
                 "# the reference table inventory. It gets no\n")


def remove_product_map_keep_coordinator(text):
    """Drop product_merchant_map but keep the coordinator registered (expt_b25)."""
    where = "run.sh"
    lines = text.split("\n")
    ab.drop_table_line(lines, "product_merchant_map", where)
    ab.remove_block(lines, where,
                    "-- Routing table for T7, which is given only product ids. A reference table",
                    ");", blank_after=True)
    ab.remove_block(lines, where,
                    "\t\tIF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'product_merchant_map'::regclass) THEN",
                    "END IF;", blank_before=True)
    ab.remove_block(lines, where,
                    "\t# No transaction inserts products or changes a product's merchant,",
                    "SQL", blank_after=True)
    ab.edit_truncate(lines, "product_merchant_map", where)
    return "\n".join(lines)


def run_sh(cell):
    w = f"{cell}/run.sh"
    if cell == "expt_b22":
        t = ab.run_sh({"T7R", "DEL"})
        t = replace_once(t, *INV_KEYS, w)
        t = replace_once(t, merchant_dist("products"), dist("products", "product_id", "none"), w)
        t = replace_once(t, merchant_dist("inventory"), dist("inventory", "product_id", "products"), w)
        t = replace_once(t, *ITEMS_LOAD, w)
    elif cell == "expt_b23":
        t = ab.run_sh({"T5R"})
        t = replace_once(t, *ITEM_KEY, w)
        t = replace_once(t, merchant_dist("orders"), dist("orders", "order_id", "none"), w)
        t = replace_once(t, merchant_dist("order_items"), dist("order_items", "order_id", "orders"), w)
        t = replace_once(t, *ITEMS_LOAD, w)
    elif cell == "expt_b24":
        t = ab.run_sh({"T7R", "DEL"})
        t = replace_once(t, *INV_KEYS, w)
        t = replace_once(t, merchant_dist("products"), dist("products", None, "none"), w)
        t = replace_once(t, merchant_dist("inventory"), dist("inventory", None, "products"), w)
        t = replace_once(t, *ITEMS_LOAD, w)
        t = replace_once(t, *INV_LOAD, w)
    elif cell == "expt_b25":
        t = remove_product_map_keep_coordinator(ab.run_sh({"DEL"}))
        t = replace_once(t, *COORD_COMMENT, w)
        t = replace_once(t, *INV_KEYS, w)
        t = replace_once(t, merchant_dist("inventory"), "PERFORM create_reference_table('inventory');", w)
    else:
        raise ValueError(cell)
    return t


def cell_files(cell):
    files = {"run.sh": run_sh(cell)}
    for tx in TX_NAMES:
        files[f"transactions/{tx}.sql"] = read(BASE / "transactions" / f"{tx}.sql")
        files[f"explain/{tx}.sql"] = read(BASE / "explain" / f"{tx}.sql")
    if cell in ("expt_b22", "expt_b24", "expt_b25"):
        # T1 leaves delegation: the merchant's products/inventory are no longer
        # on the merchant's worker. T5 routing and the T6 rollup stay on.
        files["transactions/T1_place_order.sql"] = ab.t1_original(set())
        files["explain/T1_place_order.sql"] = ab.t1_original_explain(set())
        files["transactions/T7_inventory_transfer.sql"] = read(SOURCES / "T7_inventory_transfer.sql")
        files["explain/T7_inventory_transfer.sql"] = read(SOURCES / "T7_inventory_transfer_explain.sql")
    if cell == "expt_b23":
        files["transactions/T1_place_order.sql"] = ab.t1_delegated({"T5R"})
        files["transactions/T5_update_order_status.sql"] = read(OLD / "transactions" / "T5_update_order_status.sql")
        files["explain/T5_update_order_status.sql"] = read(ab.SOURCES / "explain" / "T5_update_order_status_off.sql")
    files["optimisations.md"] = DOCS[cell]
    return files


# ------------------------------------------------------------- documentation

COMMON_LOOK = """### What to look at when this is run

- **Comparability.** Same nodes as `expt_b19` (`xcnf[17-21]`), run alone:
  `partitioning_b19/submit.sh` chains the batch with `afterany`, between the
  replicates `expt_b20` (first) and `expt_b21` (last) of `expt_b19`.
- **`schema-create.log`, `data-generation.log`, `explain.log`.** No errors.
  `data-generation.log` and the reset times in `benchmark.log` also show
  whether the new placement slows the load: the job has a 3-hour limit and
  reloads the data before every client count.
- **`pgbench_exit_code`, aborted clients, retries and serialization failures**
  at every client count.
"""

ITEMS_NOTE = """- **Data load.** `order_items` was loaded by joining `products` for each
  item's `unit_price`. That join no longer stays on one worker, so the load now
  computes the price with the formula that generated `products.price`. Every
  generated item has exactly one product (its id is the merchant's id plus a
  multiple of `NUM_MERCHANTS`), so the loaded rows are identical to
  `expt_b19`'s."""

ORIGINAL_T1 = """- **T1 is `expt_b8`'s multi-statement T1**, with the `order_merchant_map`
  insert and the `merchant_daily_sales` upsert added before `COMMIT`: the same
  T1 as the ablation's cell around `expt_b19` with only T1 delegation off. The
  delegated `place_order` relies on the merchant's products and inventory
  being on its worker; here they are not, and a delegated function opens a new
  connection for every remote statement (`expt_b16`, and
  `analysis/task4/README.md`, section 3). Compare against that cell to see
  the placement alone, and against `expt_b19` for the design as a whole."""

T7_NO_LOOKUP = """- **T7 needs no lookup.** `product_merchant_map` is gone (table, load,
  `TRUNCATE` entry), and T7 debits and credits `inventory` by `product_id`
  alone: `partitioning_b19/sources/T7_inventory_transfer.sql`. Its result is
  the same as `expt_b19`'s T7, which looked the merchant up first."""

INV_KEYS_NOTE = """- **`inventory`'s keys lead with `product_id`:** `PRIMARY KEY (product_id,
  inventory_id)` and `UNIQUE (product_id, merchant_id)`, instead of
  `(merchant_id, inventory_id)` and `(merchant_id, product_id)`. The same
  uniqueness is enforced; T7's `WHERE product_id = ...` is one index probe,
  and T2 and T4 still use the full key."""

DOCS = {
    "expt_b22": f"""### Prev: expt_b19

What-if partitioning (`partitioning_b19/README.md`): `products` and `inventory`
distributed by `product_id` in their own colocation group; every other table
stays distributed by `merchant_id`, as in `expt_b19`. Generated by
`partitioning_b19/generate.py`; do not edit by hand.

### What this tests

T7 (30% of workload B) moves stock between two products drawn at random from
all 500,000, so under `merchant_id` it needs a lookup to find each row's
merchant. Distributing the catalog by `product_id` makes T7 two updates routed
by `product_id`, with no lookup. T2 (by `product_id`), T4 (`products` joined
with `inventory` on `product_id`) and T9 stay single-shard. The cost falls on
T1: a merchant's 1-5 products now sit on different workers, so its stock checks
and decrements span workers and it can no longer be delegated whole.

### Changes from expt_b19

```sql
PERFORM create_distributed_table('products', 'product_id', colocate_with => 'none');
PERFORM create_distributed_table('inventory', 'product_id', colocate_with => 'products');
```

{INV_KEYS_NOTE}
{T7_NO_LOOKUP} The coordinator is no longer registered in Citus's metadata;
  it was only needed for that reference table.
{ORIGINAL_T1}
{ITEMS_NOTE}

{COMMON_LOOK}- **T7 and T1** against `expt_b19` and the ablation's T1-delegation-off cell: T7 should lose its lookup's
  cost; T1 pays for spanning workers.
""",
    "expt_b23": f"""### Prev: expt_b19

What-if partitioning (`partitioning_b19/README.md`): `orders` and `order_items`
distributed by `order_id` in their own colocation group; every other table
stays distributed by `merchant_id`, as in `expt_b19`. Generated by
`partitioning_b19/generate.py`; do not edit by hand.

### What this tests

T5 (10% of workload B) is given only an `order_id`. Under `merchant_id` it needs
`order_merchant_map`, which every T1 writes on a second worker. Distributing
orders by `order_id` routes T5's `UPDATE` directly and removes the map. The
cost falls on T3 (5%): a customer's latest orders are now spread over every
shard, so it becomes a multi-shard query (4 tasks with 4 shards, like T6). T1
still writes to a second worker, now the order and its items instead of the map
row.

### Changes from expt_b19

```sql
PERFORM create_distributed_table('orders', 'order_id', colocate_with => 'none');
PERFORM create_distributed_table('order_items', 'order_id', colocate_with => 'orders');
```

- **`order_items`' primary key is `(order_id, order_item_id)`** instead of
  `(merchant_id, order_item_id)`: Citus requires the distribution column in
  every primary key. `orders`' `(merchant_id, order_id)` already contains it.
- **No `order_merchant_map`** (table, load, `TRUNCATE` entry), and T5 is
  `expt_b8`'s single `UPDATE orders ... WHERE order_id = ...`, which this
  placement routes to one shard.
- **T1 is `expt_b19`'s `place_order` with step 7 (map insert) removed**, as in
  the ablation's T5-routing-off cell. It stays delegated by `merchant_id`; its order and
  item inserts now go to the order's shard, usually on another worker.
- **T3 is unchanged.** Its join of `orders` and `order_items` includes
  `order_id`, so it stays within each shard.
{ITEMS_NOTE}

{COMMON_LOOK}- **T5 and T3** against `expt_b19` and the ablation's T5-routing-off cell: T5 should
  lose its lookup; T3 pays for asking every shard.
""",
    "expt_b24": f"""### Prev: expt_b19

What-if partitioning (`partitioning_b19/README.md`): `products` and `inventory`
as single-shard tables in one colocation group, so the whole catalog is on one
worker; every other table stays distributed by `merchant_id`, as in
`expt_b19`. Generated by `partitioning_b19/generate.py`; do not edit by hand.

### What this tests

Even with T7 routed, its two rows are on different workers 3 times in 4, so
the transfer commits in two phases across workers. With all of `inventory` on
one node, T7 never spans workers and needs no lookup. The cost is a hotspot:
every catalog read and write (T1's stock checks, T2, T4, T7, T9: about 65% of
transactions) goes to that one worker.

### Changes from expt_b19

```sql
PERFORM create_distributed_table('products', NULL, colocate_with => 'none');
PERFORM create_distributed_table('inventory', NULL, colocate_with => 'products');
```

A `NULL` distribution column makes a single-shard table (Citus 12+;
`create_distributed_table` in Citus v14.1.0
`src/backend/distributed/commands/create_distributed_table.c`). Colocating the
two keeps T4's and T1's joins of `products` and `inventory` on one node.

{INV_KEYS_NOTE}
{T7_NO_LOOKUP} The coordinator is no longer registered in Citus's metadata;
  it was only needed for that reference table.
{ORIGINAL_T1}
{ITEMS_NOTE}
- **`inventory` is loaded from `generate_series`**, not with
  `INSERT INTO inventory SELECT ... FROM products`. The first run of this cell
  (job 930969) failed at that statement: Citus 14.1.0 pushes an
  `INSERT ... SELECT` between colocated single-shard tables down to the worker
  with a filter on the distribution column, which a single-shard table does not
  have, and sent `... FROM public.products_102016 products WHERE ( IS NOT NULL)`,
  a syntax error on the worker. The new statement computes the same columns
  from the same formulas (`merchant_id = 1 + (product_id - 1) % NUM_MERCHANTS`),
  so the rows are identical to `expt_b19`'s.

{COMMON_LOOK}- **`topology` of the catalog.** `pg_dist_placement` (or `explain.log`'s
  `Node:` lines for T4) names the worker that holds both tables.
- **T7, T2, T4, T9** against `expt_b19`: T7 should lose its two-phase commit;
  everything that touches the catalog queues on one worker.
""",
    "expt_b25": f"""### Prev: expt_b19

What-if partitioning (`partitioning_b19/README.md`): `inventory` as a reference
table, with a full copy on every node (the coordinator and the 4 workers);
every other table stays distributed by `merchant_id`, as in `expt_b19`.
Generated by `partitioning_b19/generate.py`; do not edit by hand.

### What this tests

With a copy of `inventory` on every node, T7 and T4 read it locally and T7
needs no lookup. The cost is write amplification: every write to a reference
table goes to every copy inside the writing transaction, and T1, T2 and T7,
about 50% of transactions, all write `inventory`.

### Changes from expt_b19

```sql
PERFORM create_reference_table('inventory');
```

{INV_KEYS_NOTE}
{T7_NO_LOOKUP} The coordinator stays registered in Citus's metadata, so it
  holds a copy of `inventory`.
{ORIGINAL_T1}

{COMMON_LOOK}- **T2 and T7** against `expt_b19`: both now write 5 copies per row.
""",
}


# ------------------------------------------------------------------- driver

def write(outputs):
    written = 0
    for d, files in outputs.items():
        target = ROOT / d
        if (target / "slurm-results").exists():
            print(f"skipping {d}: it already has slurm-results/, so its code stays as run")
            continue
        if target.exists():
            shutil.rmtree(target)
        for rel, text in files.items():
            p = target / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="\n")
        written += 1
    print(f"wrote {written} cells")


def check(outputs):
    errors = []
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
        run = files["run.sh"]
        t1 = files["transactions/T1_place_order.sql"]
        t7 = files["transactions/T7_inventory_transfer.sql"]
        expect = {
            "expt_b22": ["'products', 'product_id'", "'inventory', 'product_id', colocate_with => 'products'"],
            "expt_b23": ["'orders', 'order_id'", "'order_items', 'order_id', colocate_with => 'orders'"],
            "expt_b24": ["'products', NULL", "'inventory', NULL, colocate_with => 'products'"],
            "expt_b25": ["create_reference_table('inventory')", "citus_set_coordinator_host"],
        }[d]
        for s in expect:
            if s not in run:
                errors.append(f"{d}: run.sh lacks {s!r}")
        delegated = d == "expt_b23"
        if ("t1_function" in run) != delegated or ("\\if 0" in t1) != delegated:
            errors.append(f"{d}: T1 delegation does not match the design")
        if d == "expt_b23":
            if "order_merchant_map" in run or "order_merchant_map" in t1:
                errors.append(f"{d}: order_merchant_map still present")
            if "product_merchant_map" not in run:
                errors.append(f"{d}: product_merchant_map missing")
        else:
            if "product_merchant_map" in run or "product_merchant_map" in t7:
                errors.append(f"{d}: product_merchant_map still present")
            if "order_merchant_map" not in run or "order_merchant_map" not in t1:
                errors.append(f"{d}: T5 routing should stay on")
    for e in errors:
        print("FAIL", e)
    print("check:", "OK" if not errors else f"{len(errors)} failure(s)", f"({len(outputs)} cells)")
    return not errors


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="verify the cells on disk")
    args = ap.parse_args()
    outputs = {c: cell_files(c) for c in CELLS}
    if args.check:
        sys.exit(0 if check(outputs) else 1)
    write(outputs)


if __name__ == "__main__":
    main()
