#!/usr/bin/env python3
"""Generate the cells of the 2^4 x 3 workload-A ablation.

Four binary factors (BITS) and a three-level T1 mode m (T1_MODES). A cell is
expt_a<300 + 16*m + mask>, where mask is the sum of the enabled bits. Three
cells were run before this script existed (EXISTING); it never writes to them.
Every other cell, and the replicates in REPLICATES, is written as a standalone
experiment directory: run.sh, transactions/T1..T9, explain/T1..T9 and
optimisations.md. Nothing in a generated directory refers back to this script
at run time.

Sources, all under ablation/template/:
  run.sh      expt_a323's run.sh with factor markers. A block between
              "# @ablation-begin F" and "# @ablation-end F" is kept iff factor
              F is on ("!F": iff F is off); "@{F:text}" inside a line becomes
              text iff F is on. Every marker is removed from the output. F is
              a bit name, t1_delegation (m >= 1) or rc_lock (m == 2).
  transactions/, explain/
              <T>.sql is shared by every cell; <T>/<variant>.sql is picked per
              cell by variant_source(). The delegated T1 is stored only with
              both steps 6 and 7 (fn_both.sql, fn_both_rc.sql); the other
              levels are derived by remove_steps().

Usage:
  ablation/generate.py                      write all generated cells, the
                                            replicates and ablation/manifest.csv
  ablation/generate.py --out DIR --cells 323,331
                                            write those cell ids as DIR/expt_a<id>
                                            (for validation; any grid id allowed)
"""
import argparse
import csv
import io
import re
import sys
from pathlib import Path

ABLATION_DIR = Path(__file__).resolve().parent
REPO = ABLATION_DIR.parent
TEMPLATE = ABLATION_DIR / "template"

# (bit value, manifest column, one-line description)
BITS = [
    (1, "t5_routing",
     "T5 routing: T5 looks up `order_merchant_map`; T1 inserts the map row; "
     "`run.sh` creates, distributes, fills and truncates `order_merchant_map`"),
    (2, "t6_rollup",
     "T6 rollup: T6 reads `merchant_daily_sales`; T1 upserts the rollup row; "
     "`run.sh` creates it with `idx_mds_period`, distributes, fills and truncates it"),
    (4, "t7_routing",
     "T7 routing: T7 is `expt_b7`'s: it looks up `product_merchant_map` before "
     "`BEGIN` and routes its two `UPDATE`s; `run.sh` creates, distributes, fills "
     "and truncates `product_merchant_map`"),
    (8, "shards8",
     "Eight shards: `run.sh` sets `citus.shard_count` to `CITUS_SHARD_COUNT` "
     "(default 8, Citus's own default is 32) in the session that distributes "
     "every table, and records it in `config.txt`"),
]
BIT_NAMES = [b[1] for b in BITS]
NUM_MASKS = 16

# m -> (manifest t1_mode, description)
T1_MODES = [
    ("set", "T1 is the set-based CTE T1 inside `BEGIN`/`COMMIT`"),
    ("fn", "T1 delegation: T1 is the `place_order` distributed function, called "
     "outside a transaction block; `run.sh` creates and distributes the function"),
    ("fn_rc", "T1 delegation under READ COMMITTED: as `fn`, plus "
     "`PG_ISOLATION_LEVEL` defaults to `read committed`, `place_order`'s stock "
     "check takes `FOR UPDATE OF i`, and the function sets "
     "`plan_cache_mode = force_custom_plan`"),
]
TEMPLATE_FACTORS = BIT_NAMES + ["t1_delegation", "rc_lock"]

# Cells that were run before this script existed. Their directories hold
# results and a hand-written optimisations.md; this script never writes to them.
# Their code equals this script's output (ablation/validate.py, check 1).
EXISTING = {"expt_a323", "expt_a331", "expt_a347"}
# replicate directory expt_a<id>_<k> (the k-th extra run) -> the cell it reruns
REPLICATES = {"expt_a300_1": "expt_a300", "expt_a331_1": "expt_a331"}
REPLICATE_NAME = re.compile(r"^(expt_a\d+)_([1-9]\d*)$")
# A directory with this entry holds the results of a run: its code must not change.
RESULTS_SENTINEL = "slurm-results"
# Files of a cell that are documentation; every other file is code.
DOC_FILES = {"optimisations.md"}

TX_NAMES = [
    "T1_place_order", "T2_update_inventory", "T3_order_history",
    "T4_product_lookup", "T5_update_order_status", "T6_global_sales",
    "T7_inventory_transfer", "T8_update_customer", "T9_update_product",
]
# First line of each removable step of place_order; the step runs to the next
# blank line inclusive.
FN_STEP_HEAD = {
    6: "  -- 6. Keep the T6 rollup in step.",
    7: "  -- 7. order_merchant_map is sharded by order_id, so this row usually lives",
}
FN_STEP_DESC = {6: "6 (`merchant_daily_sales` upsert)", 7: "7 (`order_merchant_map` insert)"}
# T1 level -> steps of place_order removed for it
FN_REMOVED = {"none": (6, 7), "map": (6,), "rollup": (7,), "both": ()}

MARKER_BEGIN = re.compile(r"^# @ablation-begin (!?)(\w+)$")
MARKER_END = re.compile(r"^# @ablation-end (!?)(\w+)$")
INLINE = re.compile(r"@\{(!?)(\w+):([^}]*)\}")


def cell_id(m, mask):
    return 300 + 16 * m + mask


def cell_name(m, mask):
    return f"expt_a{cell_id(m, mask)}"


def parse_id(cid):
    """cell id -> (m, mask)"""
    if not 300 <= cid < 300 + 16 * len(T1_MODES):
        raise ValueError(f"cell id {cid} outside the grid 300..{300 + 16 * len(T1_MODES) - 1}")
    return divmod(cid - 300, 16)


def all_cells():
    return [(m, mask) for m in range(len(T1_MODES)) for mask in range(NUM_MASKS)]


def enabled(m, mask):
    """Template factors that are on for a cell."""
    on = {name for bit, name, _ in BITS if mask & bit}
    if m >= 1:
        on.add("t1_delegation")
    if m == 2:
        on.add("rc_lock")
    return on


def check_factor(name, where):
    if name not in TEMPLATE_FACTORS:
        raise ValueError(f"unknown factor {name!r} in {where}")


def render(text, on, where):
    """Strip disabled blocks and every marker from a template."""
    out, open_block = [], None  # open_block: (negated, name, keep)
    for n, line in enumerate(text.split("\n"), 1):
        begin, end = MARKER_BEGIN.match(line), MARKER_END.match(line)
        if begin:
            if open_block:
                raise ValueError(f"{where}:{n}: nested @ablation-begin")
            neg, name = begin.groups()
            check_factor(name, f"{where}:{n}")
            open_block = (neg, name, (name in on) != bool(neg))
            continue
        if end:
            if not open_block or open_block[:2] != end.groups():
                raise ValueError(f"{where}:{n}: unmatched @ablation-end")
            open_block = None
            continue
        if open_block and not open_block[2]:
            continue

        def inline(mt):
            check_factor(mt.group(2), f"{where}:{n}")
            return mt.group(3) if (mt.group(2) in on) != bool(mt.group(1)) else ""

        out.append(INLINE.sub(inline, line))
    if open_block:
        raise ValueError(f"{where}: unterminated @ablation-begin {open_block[1]}")
    result = "\n".join(out)
    if "@ablation" in result or INLINE.search(result):
        raise ValueError(f"{where}: marker left in output")
    return result


def remove_steps(text, steps, where):
    """Delete steps of place_order: from the step's head line to the next
    blank line inclusive. Each head must occur exactly once."""
    lines = text.split("\n")
    for step in steps:
        head = FN_STEP_HEAD[step]
        hits = [i for i, l in enumerate(lines) if l == head]
        if len(hits) != 1:
            raise ValueError(f"{where}: step {step} head found {len(hits)} times")
        start = hits[0]
        stop = lines.index("", start)
        del lines[start:stop + 1]
    return "\n".join(lines)


def t1_level(on):
    return {(False, False): "none", (True, False): "map",
            (False, True): "rollup", (True, True): "both"}[
        ("t5_routing" in on, "t6_rollup" in on)]


def variant_source(kind, tx, on):
    """(template file, steps of place_order removed from it) for one
    transaction (kind: transactions | explain)."""
    shared = TEMPLATE / kind / f"{tx}.sql"
    if shared.exists():
        return shared, ()
    removed = ()
    rc = "_rc" if "rc_lock" in on else ""
    if tx == "T1_place_order":
        if "t1_delegation" not in on:
            variant = f"set_{t1_level(on)}"
        elif kind == "explain":
            # Every delegation level issues the same call, so one explain file
            # per mode; fn_rc also plans the locking stock check.
            variant = f"fn{rc}"
        else:
            variant = f"fn_both{rc}"
            removed = FN_REMOVED[t1_level(on)]
    else:
        factor = {"T5_update_order_status": "t5_routing",
                  "T6_global_sales": "t6_rollup",
                  "T7_inventory_transfer": "t7_routing"}[tx]
        variant = "on" if factor in on else "off"
    path = TEMPLATE / kind / tx / f"{variant}.sql"
    if not path.exists():
        raise FileNotFoundError(f"missing template file {path}")
    return path, removed


def optimisations_md(m, mask):
    on = enabled(m, mask)
    cid = cell_id(m, mask)
    prev = "none (grid base)" if cid == 300 else "expt_a300 (grid base)"
    lines = [
        f"### Prev: {prev}",
        "",
        f"Cell {cid} (T1 mode {m} `{T1_MODES[m][0]}`, mask {mask}) of the "
        "2^4 x 3 workload-A ablation (`ablation/README.md`); every cell's "
        "factor levels are in `ablation/manifest.csv`. Generated by "
        "`ablation/generate.py` from `ablation/template/`: change the template "
        "and regenerate rather than editing this directory.",
        "",
        "Everything not listed below is the grid's shared reference: the schema, "
        "distribution, indexes, T2, T3, T4, T8, T9 and server parameters of the "
        "workload-A base design (formerly `expt_a3`, see git history), with "
        "`expt_a323`'s run configuration (`--nodelist=xcnf[0-2,4,5]`, `TEAM_ID` "
        "default 4, `PGPORT` derived from `TEAM_ID`). `run.sh` also records plans "
        "outside the timed benchmark.",
        "",
        "Enabled factors:",
        "",
        "| Factor | Description |",
        "| ------ | ----------- |",
    ]
    for value, name, desc in BITS:
        if name in on:
            lines.append(f"| `{name}` (bit {value}) | {desc} |")
    mode, desc = T1_MODES[m]
    lines.append(f"| `t1_mode={mode}` (m={m}) | {desc} |")
    lines.append("")
    level = t1_level(on)
    if m == 0:
        lines.append(f"T1 is `ablation/template/transactions/T1_place_order/set_{level}.sql`, "
                     "unchanged.")
    else:
        fn_src = "`expt_a323`" if m == 1 else "`expt_a347`"
        removed = FN_REMOVED[level]
        if removed:
            steps = " and ".join(FN_STEP_DESC[s] for s in removed)
            lines.append(
                f"T1's `place_order` is {fn_src}'s with step{'s' if len(removed) > 1 else ''} "
                f"{steps} removed from the function body. The signature, the "
                "pgbench-side statements and the rest of the body are unchanged, "
                "and the remaining steps keep the original numbering.")
            if 6 in removed:
                lines.append(
                    "Step 4 still has `RETURNING total_amount, created_at INTO "
                    "v_order_total, v_created_at`, although only step 6 read them.")
        else:
            lines.append(f"T1 is {fn_src}'s, unchanged.")
    if m == 2:
        lines += [
            "",
            "READ COMMITTED is only valid together with the stock lock, which only "
            "the delegated function has. Without `FOR UPDATE OF i`, two concurrent "
            "orders can both pass the stock check before either decrements, and the "
            "decrement has no stock predicate for READ COMMITTED to recheck: the "
            "second order is accepted against stock that is gone, and only "
            "`CHECK (quantity >= 0)` stops it, as an error rather than a clean "
            "rejection. The lock makes the second check wait for the first order "
            "and read its result. The full argument is in "
            "`expt_a347/optimisations.md`.",
        ]
    return "\n".join(lines) + "\n"


def replicate_md(of):
    if of in EXISTING:
        how = (f"`run.sh`, `transactions/` and `explain/` are copied "
               f"byte-identical from `{of}`.")
    else:
        how = (f"`run.sh`, `transactions/` and `explain/` are generated exactly "
               f"as `{of}`'s and are byte-identical to them.")
    return (f"### Prev: {of}\n\n"
            f"Replicate: a second run of `{of}`, to measure run-to-run variation "
            "(`ablation/README.md`; levels in `ablation/manifest.csv`). "
            f"{how}\n")


def cell_code(m, mask):
    """{relative path: content} for one cell's run.sh, transactions, explain."""
    on = enabled(m, mask)
    files = {"run.sh": render((TEMPLATE / "run.sh").read_text(), on,
                              "template/run.sh")}
    for kind in ("transactions", "explain"):
        for tx in TX_NAMES:
            path, removed = variant_source(kind, tx, on)
            files[f"{kind}/{tx}.sql"] = remove_steps(
                path.read_text(), removed, str(path.relative_to(TEMPLATE)))
    return files


def cell_files(m, mask):
    files = cell_code(m, mask)
    files["optimisations.md"] = optimisations_md(m, mask)
    return files


def replicate_files(of):
    if of in EXISTING:
        src = REPO / of
        files = {"run.sh": (src / "run.sh").read_text()}
        for kind in ("transactions", "explain"):
            for tx in TX_NAMES:
                files[f"{kind}/{tx}.sql"] = (src / kind / f"{tx}.sql").read_text()
    else:
        files = cell_code(*parse_id(int(of.removeprefix("expt_a"))))
    files["optimisations.md"] = replicate_md(of)
    return files


def outputs():
    """Every directory name the default run writes."""
    cells = [cell_name(m, mask) for m, mask in all_cells()]
    return [c for c in cells if c not in EXISTING] + list(REPLICATES)


def check_names():
    """Raise unless every EXISTING cell is a grid cell with a directory and every
    replicate is named expt_a<id>_<k> after the grid cell it reruns."""
    for cell in sorted(EXISTING):
        parse_id(int(cell.removeprefix("expt_a")))
        if not (REPO / cell).is_dir():
            raise FileNotFoundError(f"existing cell {cell} is missing: {REPO / cell}")
    for name, of in REPLICATES.items():
        mt = REPLICATE_NAME.match(name)
        if not mt or mt.group(1) != of:
            raise ValueError(f"replicate {name} of {of} must be named {of}_<k>, k >= 1")
        parse_id(int(of.removeprefix("expt_a")))


def write_dir(target, files):
    """Write files into target, leaving anything else there (results) alone.
    A directory with RESULTS_SENTINEL holds a run: refuse if any code file would
    change; its documentation (DOC_FILES) may still be rewritten."""
    if (target / RESULTS_SENTINEL).exists():
        stale = [rel for rel, text in files.items() if rel not in DOC_FILES
                 and (not (target / rel).exists() or (target / rel).read_text() != text)]
        if stale:
            raise RuntimeError(
                f"{target} has {RESULTS_SENTINEL}/ but its code would change "
                f"({', '.join(stale)}); refusing to rewrite a run experiment")
    for rel, text in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if rel == "run.sh":
            path.chmod(0o755)


def levels(m, mask):
    on = enabled(m, mask)
    return [*(int(n in on) for n in BIT_NAMES), T1_MODES[m][0]]


def manifest():
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["experiment", *BIT_NAMES, "t1_mode", "source"])
    for m, mask in all_cells():
        name = cell_name(m, mask)
        w.writerow([name, *levels(m, mask), "existing" if name in EXISTING else "generated"])
    for name, of in REPLICATES.items():
        w.writerow([name, *levels(*parse_id(int(of.removeprefix("expt_a")))),
                    f"replicate of {of}"])
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path,
                    help="write --cells into this directory instead of the repo")
    ap.add_argument("--cells", help="comma-separated cell ids (with --out only)")
    args = ap.parse_args()

    check_names()

    if args.out:
        if not args.cells:
            ap.error("--out requires --cells")
        for cid in (int(c) for c in args.cells.split(",")):
            m, mask = parse_id(cid)
            write_dir(args.out / cell_name(m, mask), cell_files(m, mask))
        return
    if args.cells:
        ap.error("--cells requires --out; without --out every generated cell is written")

    for m, mask in all_cells():
        if cell_name(m, mask) not in EXISTING:
            write_dir(REPO / cell_name(m, mask), cell_files(m, mask))
    for name, of in REPLICATES.items():
        write_dir(REPO / name, replicate_files(of))
    (ABLATION_DIR / "manifest.csv").write_text(manifest())


if __name__ == "__main__":
    sys.exit(main())
