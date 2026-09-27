#!/usr/bin/env python3
"""Build psql EXPLAIN scripts from the actual A7 pgbench SQL statements."""

import re
import sys
from pathlib import Path


FILES = [
    "T1_place_order.sql", "T2_update_inventory.sql", "T3_order_history.sql",
    "T4_product_lookup.sql", "T5_update_order_status.sql",
    "T6_global_sales.sql", "T7_inventory_transfer.sql",
    "T8_update_customer.sql", "T9_update_product.sql",
]
# T5 has three alternative updates; choose the SHIPPED branch. T7's two
# locator queries and both write CTEs are all measured.
SELECTED = [[0], [0], [0], [0], [0, 2], [0], [0, 1, 2, 3], [0], [0]]
EXPECTED = [1, 1, 1, 1, 4, 1, 4, 1, 1]
START = re.compile(r"^(?:WITH|SELECT|UPDATE|INSERT)\b", re.I)


def statements(path):
    found = []
    current = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not current:
            if not START.match(stripped):
                continue
            current.append(line)
        elif stripped.startswith("\\gset"):
            found.append("\n".join(current).rstrip() + ";")
            current = []
            continue
        else:
            current.append(line)
        if stripped.endswith(";"):
            found.append("\n".join(current))
            current = []
    if current:
        raise ValueError(f"Unterminated SQL statement in {path}")
    return found


def main():
    tx_dir, output_dir = map(Path, sys.argv[1:])
    output_dir.mkdir(parents=True, exist_ok=True)
    for n, name in enumerate(FILES, 1):
        found = statements(tx_dir / name)
        if len(found) != EXPECTED[n - 1]:
            raise ValueError(f"{name}: expected {EXPECTED[n - 1]} SQL statements, found {len(found)}")
        chosen = [found[i] for i in SELECTED[n - 1]]
        lines = ["\\set ON_ERROR_STOP on", "BEGIN;"]
        if n == 5:
            lines += [
                # The original lookup plan is captured below, then the same
                # route is fetched into a psql variable for its update.
                "SELECT merchant_id AS t5_merchant_id FROM order_route "
                "WHERE order_id = (:order_id)::bigint \\gset",
            ]
        if n == 7:
            lines += [
                "SELECT inventory_id AS t7_source_inventory_id, "
                "merchant_id AS t7_source_merchant_id FROM product_route "
                "WHERE product_id = (:source_product_id)::bigint \\gset",
                "SELECT inventory_id AS t7_dest_inventory_id, "
                "merchant_id AS t7_dest_merchant_id FROM product_route "
                "WHERE product_id = (:dest_product_id)::bigint \\gset",
            ]
        for index, sql in enumerate(chosen, 1):
            if n == 1:
                # Citus cannot EXPLAIN ANALYZE coordinator INSERT ... SELECT.
                # Save its planned shape, then execute the same statement once
                # with psql timing inside this rollback-only transaction.
                lines += [
                    "\\echo T1 planned statement (Citus does not support ANALYZE here)",
                    "EXPLAIN (VERBOSE, SETTINGS) " + sql,
                    "\\echo T1 actual execution time (psql Timing line follows)",
                    "\\timing on",
                    sql,
                    "\\timing off",
                ]
            else:
                lines += [f"\\echo T{n} statement {index}",
                          "EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) " + sql]
        lines += ["ROLLBACK;", ""]
        (output_dir / f"T{n}.sql").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
