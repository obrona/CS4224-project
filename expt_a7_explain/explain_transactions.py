#!/usr/bin/env python3
"""Plan every SQL statement in the copied pgbench transaction scripts."""

import argparse
import re
import subprocess
from pathlib import Path

VARIABLE = re.compile(r"(?<!:):([A-Za-z_][A-Za-z_0-9]*)")
COMMENT = re.compile(r"(?m)^\s*--.*$")


def statements(path):
    pending = ""
    for line in path.read_text().splitlines(keepends=True):
        if line.lstrip().startswith("\\"):
            # pgbench's \gset terminates the preceding SELECT without a semicolon.
            if line.lstrip().startswith("\\gset") and COMMENT.sub("", pending).strip():
                yield pending.strip()
                pending = ""
            continue
        pending += line
        while ";" in pending:
            before, pending = pending.split(";", 1)
            if COMMENT.sub("", before).strip():
                yield before.strip() + ";"
    if COMMENT.sub("", pending).strip():
        raise ValueError(f"Unterminated SQL statement in {path}")


def main():
    parser = argparse.ArgumentParser()
    for name in ("transactions", "output", "psql", "host", "port", "user", "database",
                 "num-merchants", "num-customers", "num-products", "num-orders",
                 "hot-merchants", "report-days"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    merchants = int(args.num_merchants)
    values = {
        "merchant_id": 1,
        "customer_id": 1,
        "item_count": 1,
        "inventory_change": 1,
        "order_id": 1,
        "REPORT_DAYS": int(args.report_days),
        "source_product_id": 1,
        "dest_product_id": 2,
        "transfer_qty": 1,
        "t5_merchant_id": 1,
        "t7_source_merchant_id": 1,
        "t7_source_inventory_id": 1,
        "t7_dest_merchant_id": 2 if merchants > 1 else 1,
        "t7_dest_inventory_id": 2,
        "new_email_number": 1,
        "price_increase": 1,
    }
    for slot in range(1, 6):
        values[f"product_id_{slot}"] = 1 + (slot - 1) * merchants
        values[f"qty_{slot}"] = 1
    values["product_id"] = 1

    (output / "sample-values.txt").write_text(
        "Representative pgbench bindings for EXPLAIN only; transaction SQL is not executed.\n"
        + f"NUM_MERCHANTS={args.num_merchants}\nNUM_CUSTOMERS={args.num_customers}\n"
        + f"NUM_PRODUCTS={args.num_products}\nNUM_ORDERS={args.num_orders}\n"
        + f"HOT_MERCHANTS={args.hot_merchants}\n"
        + "\n".join(f"{key}={value}" for key, value in sorted(values.items())) + "\n"
    )

    failures = []
    count = 0
    for path in sorted(Path(args.transactions).glob("T*.sql")):
        tx = path.stem.split("_", 1)[0]
        tx_dir = output / tx
        tx_dir.mkdir(exist_ok=True)
        number = 0
        for statement in statements(path):
            body = COMMENT.sub("", statement).strip()
            if re.fullmatch(r"(?:BEGIN|COMMIT|ROLLBACK)\s*;", body, re.I):
                continue
            number += 1
            missing = sorted(set(VARIABLE.findall(statement)) - values.keys())
            if missing:
                raise ValueError(f"{path}: unbound variables: {', '.join(missing)}")
            sql = VARIABLE.sub(lambda m: str(values[m.group(1)]), statement)
            cmd = [args.psql, "-X", "-v", "ON_ERROR_STOP=1", "-P", "pager=off",
                   "-h", args.host, "-p", args.port, "-U", args.user,
                   "-d", args.database, "-c", "EXPLAIN (VERBOSE, COSTS, FORMAT TEXT) " + sql]
            result = subprocess.run(cmd, text=True, capture_output=True, check=False)
            target = tx_dir / f"statement-{number:02d}.txt"
            target.write_text(
                f"Source: {path.name}, statement {number}\n"
                "EXPLAIN (VERBOSE, COSTS, FORMAT TEXT); no ANALYZE\n\n"
                + sql + "\n\n"
                + (result.stdout if result.returncode == 0 else result.stderr)
            )
            print(f"{'OK' if result.returncode == 0 else 'FAILED'} {target}", flush=True)
            if result.returncode:
                failures.append(str(target))
            count += 1
    if count == 0:
        raise ValueError("No transaction SQL statements found")
    print(f"Planned {count} statements; {len(failures)} failed", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
