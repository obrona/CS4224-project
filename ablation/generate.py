#!/usr/bin/env python3
"""Generate the cells of the 2^5 workload-A ablation on top of expt_a100.

A cell is expt_a<100 + mask>, where mask is the sum of the enabled factor bits
(see FACTORS). Seven cells are earlier experiments renamed in place (RENAMED);
this script never writes to them. Every other cell, and the replicates in
REPLICATES, is written as a standalone experiment directory: run.sh,
transactions/T1..T9, explain/T1..T9 and optimisations.md. Nothing in a
generated directory refers back to this script at run time.

Sources, all under ablation/template/:
  run.sh      expt_a115's run.sh with factor markers. A block between
              "# @ablation-begin F" and "# @ablation-end F" is kept iff factor
              F is on ("!F": iff F is off); "@{F:text}" inside a line becomes
              text iff F is on. Every marker is removed from the output.
  transactions/, explain/
              <T>.sql is shared by every cell; <T>/<variant>.sql is picked per
              cell by the functions below.

With --side b the same 32 cells are written for workload B as expt_b<100 + mask>.
B has no renamed cells: every cell is generated. transactions/ and explain/ are
the A cell's; run.sh is the A cell's with the substitutions in RUN_SH_SUBST.

Usage:
  ablation/generate.py                      write all generated cells, the
                                            replicates and ablation/manifest.csv
  ablation/generate.py --out DIR --masks 0,5
                                            write those masks as DIR/expt_a1xx
                                            (for validation; any mask allowed)
  ablation/generate.py --side b [--out DIR --masks 0,5]
                                            the same for workload B: expt_b1xx,
                                            replicates, ablation/manifest_b.csv
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

SIDES = ("a", "b")

# (bit value, manifest column, one-line description, {side: source experiment})
FACTORS = [
    (1, "t5_routing",
     "T5 routing: T5 looks up `order_merchant_map`; T1 inserts the map row; "
     "`run.sh` creates, distributes, fills and truncates `order_merchant_map`",
     {"a": "`expt_a101` (formerly `expt_a4`)",
      "b": "`expt_b5`"}),
    (2, "t6_rollup",
     "T6 rollup: T6 reads `merchant_daily_sales`; T1 upserts the rollup row; "
     "`run.sh` creates it with `idx_mds_period`, distributes, fills and truncates it",
     {"a": "`expt_a102` (formerly `expt_a5`)",
      "b": "`expt_b6`"}),
    (4, "t7_routing",
     "T7 routing: T7 looks up `product_merchant_map` before `BEGIN` and routes "
     "its two `UPDATE`s; `run.sh` creates, distributes, fills and truncates "
     "`product_merchant_map`",
     {"a": "`expt_b7` (identical T7 in `expt_a105`, formerly `expt_a8`)",
      "b": "`expt_b4` (identical T7 in `expt_b7`)"}),
    (8, "t1_delegation",
     "T1 delegation: T1 is the `place_order` distributed function, called "
     "outside a transaction block; `run.sh` creates and distributes the function",
     {"a": "`expt_a111` (formerly `expt_a7`)",
      "b": "`expt_b7`"}),
    (16, "repeatable_read",
     "Repeatable read: `PG_ISOLATION_LEVEL` defaults to `repeatable read` "
     "instead of `serializable`",
     {"a": "`origin/tl` `expt_a7`",
      "b": "`origin/tl` `expt_a7` (later also `expt_b14` on branch `b-side`)"}),
]
FACTOR_NAMES = [f[1] for f in FACTORS]
NUM_CELLS = 32

# mask -> (current directory, directory it was renamed from)
RENAMED = {
    0: ("expt_a100", "expt_a3"),
    1: ("expt_a101", "expt_a4"),
    2: ("expt_a102", "expt_a5"),
    3: ("expt_a103", "expt_a6"),
    5: ("expt_a105", "expt_a8"),
    11: ("expt_a111", "expt_a7"),
    15: ("expt_a115", "expt_a9"),
}
# replicate directory -> the cell it is a second run of
REPLICATES = {"expt_a200": "expt_a100", "expt_a215": "expt_a115"}

# Per side: renamed cells (B has none; every B cell is generated), replicates,
# manifest file name.
RENAMED_BY_SIDE = {"a": RENAMED, "b": {}}
REPLICATES_BY_SIDE = {
    "a": REPLICATES,
    "b": {"expt_b200": "expt_b100", "expt_b215": "expt_b115"},
}
MANIFEST = {"a": "manifest.csv", "b": "manifest_b.csv"}

# (old, new) textual substitutions applied to the rendered run.sh, per side.
# Each old string must occur exactly once in the rendered run.sh.
RUN_SH_SUBST = {
    "a": [],
    "b": [
        ("# Pin every A-side run to one fixed node set. The compute nodes are shared and\n"
         "# this job does not request --exclusive, so an unpinned run measures whoever\n"
         "# else happens to be on the node as much as the design change. This is the\n"
         "# reference set: a throughput delta is only attributable against another run\n"
         "# from these same five nodes.\n"
         "# xcnf2 is deliberately not in the list - it has no /home mount, so initdb is\n"
         "# not visible there and the job dies at startup with exit 127.\n"
         "#SBATCH --nodelist=xcnf[1,3-6]\n",
         "# Pin every B-side run to one fixed node set, disjoint from the A-side set so\n"
         "# the two series can run concurrently without sharing hardware. The compute\n"
         "# nodes are shared and this job does not request --exclusive, so an unpinned\n"
         "# run measures whoever else is on the node as much as the design change.\n"
         "#SBATCH --nodelist=xcnf[17-21]\n"),
        ("#SBATCH --mail-user=alice_and_bob@u.nus.edu\n",
         "#SBATCH --mail-user=e1334269@u.nus.edu\n"),
        ("TEAM_ID=${TEAM_ID:-99}\n", "TEAM_ID=${TEAM_ID:-4}\n"),
        ('WORKLOAD="${WORKLOAD:-A}"\n', 'WORKLOAD="${WORKLOAD:-B}"\n'),
    ],
}

TX_NAMES = [
    "T1_place_order", "T2_update_inventory", "T3_order_history",
    "T4_product_lookup", "T5_update_order_status", "T6_global_sales",
    "T7_inventory_transfer", "T8_update_customer", "T9_update_product",
]
# Which step(s) of expt_a111's place_order each delegation variant removes.
FN_REMOVED_STEPS = {
    "none": "steps 6 (`merchant_daily_sales` upsert) and 7 (`order_merchant_map` insert)",
    "map": "step 6 (`merchant_daily_sales` upsert)",
    "rollup": "step 7 (`order_merchant_map` insert)",
    "both": None,
}
# The cell whose place_order is fn_both, per side.
FN_T1_SOURCE = {"a": "expt_a111", "b": "expt_b7"}
# The sentence naming where each set-based T1 comes from, per side.
SET_T1_SENTENCE = {
    "a": {level: f"T1 is {src}'s set-based T1, unchanged." for level, src in {
        "none": "`expt_a100`", "map": "`expt_a101`",
        "rollup": "`expt_a102`", "both": "`expt_a103`"}.items()},
    "b": {
        "none": "T1 is `expt_b3`'s set-based T1, unchanged.",
        "map": "T1 is `expt_b5`'s set-based T1, unchanged.",
        "rollup": "T1 is `expt_a102`'s set-based T1, unchanged; no workload-B "
                  "experiment has the rollup upsert without the map insert.",
        "both": "T1 is `expt_b6`'s set-based T1, unchanged.",
    },
}

MARKER_BEGIN = re.compile(r"^# @ablation-begin (!?)(\w+)$")
MARKER_END = re.compile(r"^# @ablation-end (!?)(\w+)$")
INLINE = re.compile(r"@\{(!?)(\w+):([^}]*)\}")


def cell_name(mask, side):
    return f"expt_{side}{100 + mask}"


def cell_mask(name, side):
    return int(name.removeprefix(f"expt_{side}")) - 100


def enabled(mask):
    return {name for bit, name, _, _ in FACTORS if mask & bit}


def check_factor(name, where):
    if name not in FACTOR_NAMES:
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

        def inline(m):
            check_factor(m.group(2), f"{where}:{n}")
            return m.group(3) if (m.group(2) in on) != bool(m.group(1)) else ""

        out.append(INLINE.sub(inline, line))
    if open_block:
        raise ValueError(f"{where}: unterminated @ablation-begin {open_block[1]}")
    result = "\n".join(out)
    if "@ablation" in result or INLINE.search(result):
        raise ValueError(f"{where}: marker left in output")
    return result


def run_sh(on, side):
    """The rendered template run.sh with the side's substitutions applied."""
    text = render((TEMPLATE / "run.sh").read_text(), on, "template/run.sh")
    for old, new in RUN_SH_SUBST[side]:
        count = text.count(old)
        if count != 1:
            raise ValueError(f"side {side}: run.sh substitution matched {count} "
                             f"times, expected 1: {old.splitlines()[-1]!r}")
        text = text.replace(old, new)
    return text


def t1_level(on):
    return {(False, False): "none", (True, False): "map",
            (False, True): "rollup", (True, True): "both"}[
        ("t5_routing" in on, "t6_rollup" in on)]


def variant_file(kind, tx, on):
    """Template file for one transaction (kind: transactions | explain)."""
    shared = TEMPLATE / kind / f"{tx}.sql"
    if shared.exists():
        return shared
    if tx == "T1_place_order":
        if "t1_delegation" in on:
            # Every delegation variant issues the same call, so one explain file.
            variant = "fn" if kind == "explain" else f"fn_{t1_level(on)}"
        else:
            variant = f"set_{t1_level(on)}"
    else:
        factor = {"T5_update_order_status": "t5_routing",
                  "T6_global_sales": "t6_rollup",
                  "T7_inventory_transfer": "t7_routing"}[tx]
        variant = "on" if factor in on else "off"
    path = TEMPLATE / kind / tx / f"{variant}.sql"
    if not path.exists():
        raise FileNotFoundError(f"missing template file {path}")
    return path


def optimisations_intro(mask, side):
    """The paragraphs of optimisations.md before the factor table."""
    if side == "a":
        return [
            "### Prev: expt_a100 (base)",
            "",
            f"Cell {mask} of the 2^5 workload-A ablation (`ablation/README.md`); "
            "every cell's factor levels are in `ablation/manifest.csv`. Generated by "
            "`ablation/generate.py` from `ablation/template/`: change the template "
            "and regenerate rather than editing this directory.",
            "",
            "Everything not listed below is exactly `expt_a100`'s (formerly "
            "`expt_a3`): schema, distribution, indexes, T2, T3, T4, T8, T9 and "
            "server parameters. `run.sh` also records plans outside the timed "
            "benchmark, as `expt_a115` does.",
        ]
    return [
        "### Prev: expt_b100 (base)",
        "",
        f"Cell {mask} of the 2^5 workload-B ablation (`ablation/README.md`); "
        "every cell's factor levels are in `ablation/manifest_b.csv`. Generated by "
        "`ablation/generate.py --side b` from `ablation/template/`: change the "
        "template and regenerate rather than editing this directory.",
        "",
        "Every cell of the workload-B ablation is generated; none is a renamed "
        "earlier experiment. `expt_b100` is `expt_b3`'s code on the A-ablation "
        f"template. `transactions/` and `explain/` are byte-identical to "
        f"`{cell_name(mask, 'a')}`'s, the workload-A cell with the same mask; "
        "`run.sh` differs from it only in the node pin (`xcnf[17-21]`), the mail "
        "user and the `TEAM_ID` and `WORKLOAD` defaults.",
        "",
        "Everything not listed below is exactly `expt_b100`'s: schema, "
        "distribution, indexes, T2, T3, T4, T8, T9 and server parameters. "
        "`run.sh` also records plans outside the timed benchmark, as "
        "`expt_a115` does.",
    ]


def optimisations_md(mask, side):
    on = enabled(mask)
    lines = optimisations_intro(mask, side) + [
        "",
        "Enabled factors:",
        "",
        "| Bit (value) | Factor | Source |",
        "| ----------- | ------ | ------ |",
    ]
    for index, (value, name, desc, source) in enumerate(FACTORS):
        if name in on:
            lines.append(f"| {index} ({value}) | {desc} | {source[side]} |")
    lines.append("")
    level = t1_level(on)
    fn_source = FN_T1_SOURCE[side]
    if "t1_delegation" in on:
        removed = FN_REMOVED_STEPS[level]
        if removed:
            lines.append(
                f"T1's `place_order` is `{fn_source}`'s with {removed} removed from "
                "the function body. The signature, the pgbench-side statements and "
                "the rest of the body are unchanged, and the remaining steps keep "
                f"`{fn_source}`'s numbering.")
            if "t6_rollup" not in on:
                lines.append(
                    "Step 4 still has `RETURNING total_amount, created_at INTO "
                    "v_order_total, v_created_at`, although only step 6 read them.")
        else:
            lines.append(f"T1 is `{fn_source}`'s, unchanged.")
    else:
        lines.append(SET_T1_SENTENCE[side][level])
    if "repeatable_read" in on:
        lines += [
            "",
            "The default transaction isolation level on every node is "
            "`repeatable read`, not `serializable`. The teammate's argument for "
            "why the transactions stay correct under it, and its limits, is in "
            "`git show origin/tl:expt_a7/optimisations.md`.",
        ]
    return "\n".join(lines) + "\n"


def replicate_md(of, side):
    lines = [
        f"### Prev: {of}",
        "",
        f"Replicate: a second run of `{of}`, to measure run-to-run variation "
        f"(`ablation/README.md`; levels in `ablation/{MANIFEST[side]}`). "
        f"`transactions/` and `explain/` are byte-identical to `{of}`'s.",
        "",
    ]
    if of == "expt_a100":
        lines.append(
            "`run.sh` is generated from `ablation/template/run.sh` with every "
            "factor off, not copied: it is `expt_a100`'s `run.sh` plus the native "
            "EXPLAIN step, so this run also records plans, which `expt_a100`'s "
            "run did not.")
    else:
        lines.append(f"`run.sh` is byte-identical to `{of}`'s.")
    return "\n".join(lines) + "\n"


def cell_files(mask, side):
    """{relative path: content} for one generated cell."""
    on = enabled(mask)
    files = {"run.sh": run_sh(on, side)}
    for kind in ("transactions", "explain"):
        for tx in TX_NAMES:
            files[f"{kind}/{tx}.sql"] = variant_file(kind, tx, on).read_text()
    files["optimisations.md"] = optimisations_md(mask, side)
    return files


def replicate_files(of, side):
    mask = cell_mask(of, side)
    if mask not in RENAMED_BY_SIDE[side]:
        # A generated cell: render it the same way, so the code is identical.
        files = cell_files(mask, side)
    else:
        src = REPO / of
        files = {}
        if of == "expt_a100":
            files["run.sh"] = run_sh(set(), side)
        else:
            files["run.sh"] = (src / "run.sh").read_text()
        for kind in ("transactions", "explain"):
            for tx in TX_NAMES:
                files[f"{kind}/{tx}.sql"] = (src / kind / f"{tx}.sql").read_text()
    files["optimisations.md"] = replicate_md(of, side)
    return files


def write_dir(target, files):
    """Write files into target, leaving anything else there (results) alone."""
    if (target / "slurm-results").exists():
        stale = [rel for rel, text in files.items()
                 if not (target / rel).exists() or (target / rel).read_text() != text]
        if stale:
            raise RuntimeError(
                f"{target} has slurm-results/ but its code would change "
                f"({', '.join(stale)}); refusing to rewrite a run experiment")
    for rel, text in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if rel == "run.sh":
            path.chmod(0o755)


def manifest(side):
    renamed = RENAMED_BY_SIDE[side]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["experiment", "mask", *FACTOR_NAMES, "source"])
    for mask in range(NUM_CELLS):
        on = enabled(mask)
        source = f"renamed from {renamed[mask][1]}" if mask in renamed else "generated"
        w.writerow([cell_name(mask, side), mask, *(int(n in on) for n in FACTOR_NAMES), source])
    for name, of in REPLICATES_BY_SIDE[side].items():
        mask = cell_mask(of, side)
        on = enabled(mask)
        w.writerow([name, mask, *(int(n in on) for n in FACTOR_NAMES), f"replicate of {of}"])
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--side", choices=SIDES, default="a",
                    help="workload side: a (expt_a1xx) or b (expt_b1xx)")
    ap.add_argument("--out", type=Path,
                    help="write --masks into this directory instead of the repo")
    ap.add_argument("--masks", help="comma-separated masks (with --out only)")
    args = ap.parse_args()
    side = args.side
    renamed = RENAMED_BY_SIDE[side]

    for mask, (current, _) in renamed.items():
        if current != cell_name(mask, side):
            raise AssertionError(f"RENAMED[{mask}] is {current}, expected {cell_name(mask, side)}")
        if not (REPO / current).is_dir():
            raise FileNotFoundError(f"renamed cell {current} is missing from {REPO}")

    if args.out:
        if not args.masks:
            ap.error("--out requires --masks")
        for mask in (int(m) for m in args.masks.split(",")):
            if not 0 <= mask < NUM_CELLS:
                ap.error(f"mask {mask} out of range 0..{NUM_CELLS - 1}")
            write_dir(args.out / cell_name(mask, side), cell_files(mask, side))
        return
    if args.masks:
        ap.error("--masks requires --out; without --out every generated cell is written")

    for mask in range(NUM_CELLS):
        if mask not in renamed:
            write_dir(REPO / cell_name(mask, side), cell_files(mask, side))
    for name, of in REPLICATES_BY_SIDE[side].items():
        write_dir(REPO / name, replicate_files(of, side))
    (ABLATION_DIR / MANIFEST[side]).write_text(manifest(side))


if __name__ == "__main__":
    sys.exit(main())
