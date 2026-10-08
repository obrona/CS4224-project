#!/usr/bin/env python3
"""Generate the cells of the 2^4 x 2 workload-A and workload-B ablations.

Four binary factors (BITS) and a two-level T1 mode m (T1_MODES). A cell is
expt_<side><300 + 16*m + mask>, where side is a or b (workload) and mask is the
sum of the enabled bits. Two A cells were run before this script existed
(EXISTING); it never writes to them. Eighteen B directories are runs of the
earlier 2^5 workload-B ablation renamed into this grid (RENAMED); it writes
only their optimisations.md. Every other cell, and the replicates in
REPLICATES, is written as a standalone experiment directory: run.sh,
transactions/T1..T9, explain/T1..T9 and optimisations.md. Nothing in a
generated directory refers back to this script at run time.

Sources, all under ablation/template/:
  run.sh      expt_a323's run.sh with factor markers. A block between
              "# @ablation-begin F" and "# @ablation-end F" is kept iff factor
              F is on ("!F": iff F is off); "@{F:text}" inside a line becomes
              text iff F is on. Every marker is removed from the output. F is
              a bit name or t1_delegation (m == 1).
  transactions/, explain/
              <T>.sql is shared by every cell; <T>/<variant>.sql is picked per
              cell by variant_source(). The delegated T1 is stored only with
              both steps 6 and 7 (fn_both.sql); the other levels are derived
              by remove_steps().
The side-b run.sh is the rendered template with RUN_SH_SUBST["b"] applied;
transactions/ and explain/ do not depend on the side.

Usage:
  ablation/generate.py [--side a|b]         write all generated cells, the
                                            replicates and ablation/manifest.csv
                                            (side b: manifest_b.csv)
  ablation/generate.py [--side a|b] --out DIR --cells 323,331
                                            write those cell ids as DIR/expt_<side><id>
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
]
TEMPLATE_FACTORS = BIT_NAMES + ["t1_delegation"]

SIDES = ("a", "b")
MANIFEST = {"a": "manifest.csv", "b": "manifest_b.csv"}
# Cells that were run before this script existed. Their directories hold
# results and a hand-written optimisations.md; this script never writes to them.
# Their code equals this script's output (ablation/validate.py, check 1).
EXISTING = {"a": {"expt_a323", "expt_a331"}, "b": set()}
# Runs of the 2^5 workload-B ablation (branch ablation-b) that are exactly a
# cell or replicate of this grid, moved to their grid names: name -> (name in
# the 2^5 ablation, commit on ablation-b that added its result). That design's
# bits were T5R=1 T6R=2 T7R=4 DEL=8 RR=16 with 32 shards; its DEL=0/1, RR=0
# cells are this grid's m=0/1 cells with shards8 off. Their code is kept as run
# and equals this script's output except for PGPORT_AS_RUN (validate.py,
# check 1); this script writes only their optimisations.md.
RENAMED = {"a": {}, "b": {
    "expt_b300": ("expt_b100", "d26361a"), "expt_b301": ("expt_b101", "d26361a"),
    "expt_b302": ("expt_b102", "d26361a"), "expt_b303": ("expt_b103", "d26361a"),
    "expt_b304": ("expt_b104", "d26361a"), "expt_b305": ("expt_b105", "fa7d727"),
    "expt_b306": ("expt_b106", "fa7d727"), "expt_b307": ("expt_b107", "fa7d727"),
    "expt_b316": ("expt_b108", "d26361a"), "expt_b317": ("expt_b109", "d26361a"),
    "expt_b318": ("expt_b110", "d26361a"), "expt_b319": ("expt_b111", "d26361a"),
    "expt_b320": ("expt_b112", "d26361a"), "expt_b321": ("expt_b113", "fa7d727"),
    "expt_b322": ("expt_b114", "d26361a"), "expt_b323": ("expt_b115", "d26361a"),
    "expt_b300_1": ("expt_b200", "d26361a"), "expt_b323_1": ("expt_b215", "fa7d727"),
}}
# replicate directory expt_<side><id>_<k> (the k-th extra run) -> the cell it reruns
REPLICATES = {
    "a": {"expt_a300_1": "expt_a300", "expt_a331_1": "expt_a331"},
    # expt_b300_1 and expt_b323_1 are renamed (same batch as their cells);
    # expt_b300_2 reruns a renamed cell in the new batch, to measure drift
    # between the two batches.
    "b": {"expt_b300_1": "expt_b300", "expt_b300_2": "expt_b300",
          "expt_b323_1": "expt_b323", "expt_b331_1": "expt_b331"},
}
REPLICATE_NAME = re.compile(r"^(expt_[ab]\d+)_([1-9]\d*)$")
# (old, new) substitutions applied to the rendered template run.sh, per side;
# each old text must occur exactly once (run_sh). The template's TEAM_ID
# default is already 4 on both sides.
RUN_SH_SUBST = {"a": [], "b": [
    ("# Pin every A-side run to one fixed node set. The compute nodes are shared and\n"
     "# this job does not request --exclusive, so an unpinned run measures whoever\n"
     "# else happens to be on the node as much as the design change. This is the\n"
     "# reference set: a throughput delta is only attributable against another run\n"
     "# from these same five nodes.\n"
     "# xcnf2 is deliberately not in the list - it has no /home mount, so initdb is\n"
     "# not visible there and the job dies at startup with exit 127.\n"
     "#SBATCH --nodelist=xcnf[0-2,4,5]\n"
     "# xcnf3 has no /home mount at the time of this run and xcnf6 is busy with another\n"
     "# team's jobs, so this set replaces xcnf[1,3-6]; compare only against runs from it.\n",
     # The renamed cells' block, verbatim, so that they differ from this
     # output only in PGPORT_AS_RUN.
     "# Pin every B-side run to one fixed node set, disjoint from the A-side set so\n"
     "# the two series can run concurrently without sharing hardware. The compute\n"
     "# nodes are shared and this job does not request --exclusive, so an unpinned\n"
     "# run measures whoever else is on the node as much as the design change.\n"
     "#SBATCH --nodelist=xcnf[17-21]\n"),
    ("#SBATCH --mail-user=alice_and_bob@u.nus.edu\n",
     "#SBATCH --mail-user=e1334269@u.nus.edu\n"),
    ('WORKLOAD="${WORKLOAD:-A}"\n', 'WORKLOAD="${WORKLOAD:-B}"\n'),
]}
# The PGPORT lines of this script's run.sh, and of the renamed B cells' run.sh
# as run, which allowed a PGPORT override. Every job of the 2^5 workload-B
# ablation was submitted with PGPORT unset (one TEAM_ID per port slot, 104 to
# 704), so the port was TEAM_ID + 5432 under both.
PGPORT_AS_GENERATED = (
    "# Port derived from the team ID; concurrent jobs use TEAM_ID 4, 104, 204, ...\n"
    "PGPORT=$((10#${TEAM_ID} + 5432))\n")
PGPORT_AS_RUN = (
    "# PGPORT may be overridden so several experiments can share the pinned node set\n"
    "# concurrently; each needs its own port because they run on the same hosts.\n"
    "# Unset, it is exactly the per-team port the project spec assigns.\n"
    'PGPORT="${PGPORT:-$((10#${TEAM_ID} + 5432))}"\n')
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


def cell_name(m, mask, side):
    return f"expt_{side}{cell_id(m, mask)}"


def parse_id(cid):
    """cell id -> (m, mask)"""
    if not 300 <= cid < 300 + 16 * len(T1_MODES):
        raise ValueError(f"cell id {cid} outside the grid 300..{300 + 16 * len(T1_MODES) - 1}")
    return divmod(cid - 300, 16)


def parse_name(name, side):
    """cell name expt_<side><id> -> (m, mask)"""
    prefix = f"expt_{side}"
    if not name.startswith(prefix) or not name[len(prefix):].isdigit():
        raise ValueError(f"{name!r} is not a side-{side} cell name {prefix}<id>")
    return parse_id(int(name[len(prefix):]))


def all_cells():
    return [(m, mask) for m in range(len(T1_MODES)) for mask in range(NUM_MASKS)]


def enabled(m, mask):
    """Template factors that are on for a cell."""
    on = {name for bit, name, _ in BITS if mask & bit}
    if m == 1:
        on.add("t1_delegation")
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
    if tx == "T1_place_order":
        if "t1_delegation" not in on:
            variant = f"set_{t1_level(on)}"
        elif kind == "explain":
            # Every delegation level issues the same call, so one explain file.
            variant = "fn"
        else:
            variant = "fn_both"
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


def factor_lines(m, mask):
    """The enabled-factor table and the T1 description of a cell's
    optimisations.md; the same on both sides."""
    on = enabled(m, mask)
    lines = [
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
        removed = FN_REMOVED[level]
        if removed:
            steps = " and ".join(FN_STEP_DESC[s] for s in removed)
            lines.append(
                f"T1's `place_order` is `expt_a323`'s with step{'s' if len(removed) > 1 else ''} "
                f"{steps} removed from the function body. The signature, the "
                "pgbench-side statements and the rest of the body are unchanged, "
                "and the remaining steps keep the original numbering.")
            if 6 in removed:
                lines.append(
                    "Step 4 still has `RETURNING total_amount, created_at INTO "
                    "v_order_total, v_created_at`, although only step 6 read them.")
        else:
            lines.append("T1 is `expt_a323`'s, unchanged.")
    return lines


def cell_heading(m, mask, side):
    """'### Prev' line and the sentence placing a cell in its side's grid."""
    cid = cell_id(m, mask)
    prev = "none (grid base)" if cid == 300 else f"{cell_name(0, 0, side)} (grid base)"
    workload = {"a": "workload-A ablation (`ablation/README.md`)",
                "b": "workload-B ablation (`ablation/README.md`, \"Workload B\")"}[side]
    return [
        f"### Prev: {prev}",
        "",
        f"Cell {cid} (T1 mode {m} `{T1_MODES[m][0]}`, mask {mask}) of the "
        f"2^4 x 2 {workload}; every cell's factor levels are in "
        f"`ablation/{MANIFEST[side]}`.",
    ]


def optimisations_md(m, mask, side):
    cid = cell_id(m, mask)
    head = cell_heading(m, mask, side)
    if side == "a":
        head[-1] += (" Generated by `ablation/generate.py` from `ablation/template/`: "
                     "change the template and regenerate rather than editing this "
                     "directory.")
        reference = [
            "Everything not listed below is the grid's shared reference: the schema, "
            "distribution, indexes, T2, T3, T4, T8, T9 and server parameters of the "
            "workload-A base design (formerly `expt_a3`, see git history), with "
            "`expt_a323`'s run configuration (`--nodelist=xcnf[0-2,4,5]`, `TEAM_ID` "
            "default 4, `PGPORT` derived from `TEAM_ID`). `run.sh` also records plans "
            "outside the timed benchmark.",
        ]
    else:
        head[-1] += (" Generated by `ablation/generate.py --side b` from "
                     "`ablation/template/`: change the template and regenerate rather "
                     "than editing this directory.")
        reference = [
            f"`transactions/` and `explain/` are byte-identical to `expt_a{cid}`'s, the "
            "workload-A cell with the same factor levels, and `run.sh` differs from "
            f"`expt_a{cid}`'s only in the node pin (`--nodelist=xcnf[17-21]`, the B-side "
            "node set: disjoint from A's and shared by every B cell), the mail user and "
            "the `WORKLOAD` default (`B`).",
            "",
            "Everything not listed below is therefore the grid's shared reference, as on "
            "workload A: the schema, distribution, indexes, T2, T3, T4, T8, T9 and server "
            "parameters of the workload-A base design (formerly `expt_a3`, see git "
            "history), `TEAM_ID` default 4 and `PGPORT` derived from `TEAM_ID`. `run.sh` "
            "also records plans outside the timed benchmark.",
        ]
    return "\n".join([*head, "", *reference, "", *factor_lines(m, mask)]) + "\n"


def fenced(text):
    return ["```sh", *text.rstrip("\n").split("\n"), "```"]


def renamed_md(name, side):
    """optimisations.md of a directory in RENAMED[side]: a run of the 2^5
    workload-B ablation, kept as run under its grid name."""
    old, commit = RENAMED[side][name]
    origin = ("of the 2^5 workload-B ablation (branch `ablation-b`; bits T5R=1 T6R=2 "
              "T7R=4 DEL=8 RR=16, Citus's default 32 shards)")
    result = (f"Its result (`slurm-results/`, `citus-*.out`, `citus-*.err`) was added on "
              f"that branch in {commit}; the raw logs are gzipped here "
              "(`ablation/README.md`, \"Stored results\").")
    if name in REPLICATES[side]:
        of = REPLICATES[side][name]
        return "\n".join([
            f"### Prev: {of}",
            "",
            f"Replicate: a second run of `{of}`, to measure run-to-run variation "
            f"(`ablation/README.md`, \"Workload B\"; levels in `ablation/{MANIFEST[side]}`). "
            f"Renamed from `{old}` {origin}, where it replicated `{RENAMED[side][of][0]}`, "
            f"which is now `{of}`. {result}",
            "",
            f"`run.sh`, `transactions/` and `explain/` are kept as run and are "
            f"byte-identical to `{of}`'s, including the PGPORT lines in which both differ "
            f"from the generator's output (`{of}/optimisations.md`).",
        ]) + "\n"
    m, mask = parse_name(name, side)
    old_mask = int(old.removeprefix("expt_b")) - 100
    if old_mask != mask + 8 * m:
        raise ValueError(f"{name} (m={m}, mask={mask}) is not 2^5 cell {old} (DEL=8)")
    return "\n".join([
        *cell_heading(m, mask, side),
        "",
        f"Renamed from `{old}` {origin}, where it was mask {old_mask}: DEL={m} and "
        f"RR=0, which is this grid's T1 mode `{T1_MODES[m][0]}` with `shards8` off. "
        f"{result}",
        "",
        "Its `run.sh`, `transactions/` and `explain/` are kept as run. They are "
        "byte-identical to `ablation/generate.py --side b`'s output for this cell "
        "except for `run.sh`'s PGPORT lines, which as run are",
        "",
        *fenced(PGPORT_AS_RUN),
        "",
        "where the generator writes",
        "",
        *fenced(PGPORT_AS_GENERATED),
        "",
        "Every job of the 2^5 workload-B ablation was submitted with `PGPORT` unset "
        "(one `TEAM_ID` per port slot, 104 to 704), so the port was `TEAM_ID + 5432` "
        "under both. `ablation/validate.py --side b` checks that nothing else differs.",
        "",
        *factor_lines(m, mask),
    ]) + "\n"


def replicate_md(name, of, side):
    """optimisations.md of a replicate this script writes."""
    if of in RENAMED[side]:
        same_batch = [of] + [r for r, o in REPLICATES[side].items()
                             if o == of and r in RENAMED[side]]
        listed = " and ".join(f"`{r}`" for r in same_batch)
        return (
            f"### Prev: {of}\n\n"
            f"Replicate: a run of `{of}`'s code in the new batch of workload-B runs, "
            f"the cells `ablation/generate.py --side b` writes (`ablation/README.md`, "
            f"\"Workload B\"; levels in `ablation/{MANIFEST[side]}`). {listed} "
            f"{'are runs' if len(same_batch) > 1 else 'is a run'} of the earlier 2^5 "
            "workload-B ablation, renamed; comparing this run with "
            f"{'them' if len(same_batch) > 1 else 'it'} measures the drift between the "
            "reused batch and the new batch, on top of run-to-run variation. "
            f"`run.sh`, `transactions/` and `explain/` are generated exactly as "
            f"`{of}`'s would be: `transactions/` and `explain/` are byte-identical to "
            f"`{of}`'s, and `run.sh` differs from `{of}`'s only in the PGPORT lines "
            f"`{of}` kept from its run (`{of}/optimisations.md`).\n")
    if of in EXISTING[side]:
        how = (f"`run.sh`, `transactions/` and `explain/` are copied "
               f"byte-identical from `{of}`.")
    else:
        how = (f"`run.sh`, `transactions/` and `explain/` are generated exactly "
               f"as `{of}`'s and are byte-identical to them.")
    return (f"### Prev: {of}\n\n"
            f"Replicate: a second run of `{of}`, to measure run-to-run variation "
            f"(`ablation/README.md`; levels in `ablation/{MANIFEST[side]}`). "
            f"{how}\n")


def run_sh(on, side):
    """The rendered template run.sh with the side's substitutions applied."""
    text = render((TEMPLATE / "run.sh").read_text(), on, "template/run.sh")
    for old, new in RUN_SH_SUBST[side]:
        hits = text.count(old)
        if hits != 1:
            raise ValueError(f"side {side}: run.sh substitution of {old.splitlines()[0]!r} "
                             f"matched {hits} times, expected exactly 1")
        text = text.replace(old, new)
    return text


def cell_code(m, mask, side):
    """{relative path: content} for one cell's run.sh, transactions, explain."""
    on = enabled(m, mask)
    files = {"run.sh": run_sh(on, side)}
    for kind in ("transactions", "explain"):
        for tx in TX_NAMES:
            path, removed = variant_source(kind, tx, on)
            files[f"{kind}/{tx}.sql"] = remove_steps(
                path.read_text(), removed, str(path.relative_to(TEMPLATE)))
    return files


def cell_files(m, mask, side):
    files = cell_code(m, mask, side)
    files["optimisations.md"] = optimisations_md(m, mask, side)
    return files


def replicate_files(name, of, side):
    if of in EXISTING[side]:
        src = REPO / of
        files = {"run.sh": (src / "run.sh").read_text()}
        for kind in ("transactions", "explain"):
            for tx in TX_NAMES:
                files[f"{kind}/{tx}.sql"] = (src / kind / f"{tx}.sql").read_text()
    else:
        files = cell_code(*parse_name(of, side), side)
    files["optimisations.md"] = replicate_md(name, of, side)
    return files


def outputs(side):
    """Every directory whose code the default run writes."""
    cells = [cell_name(m, mask, side) for m, mask in all_cells()]
    return ([c for c in cells if c not in EXISTING[side] and c not in RENAMED[side]]
            + [r for r in REPLICATES[side] if r not in RENAMED[side]])


def check_names(side):
    """Raise unless every EXISTING cell is a grid cell with a directory, every
    replicate is named expt_<side><id>_<k> after the grid cell it reruns, and
    every RENAMED directory is a cell or replicate holding its run."""
    for cell in sorted(EXISTING[side]):
        parse_name(cell, side)
        if not (REPO / cell).is_dir():
            raise FileNotFoundError(f"existing cell {cell} is missing: {REPO / cell}")
    for name, of in REPLICATES[side].items():
        mt = REPLICATE_NAME.match(name)
        if not mt or mt.group(1) != of:
            raise ValueError(f"replicate {name} of {of} must be named {of}_<k>, k >= 1")
        parse_name(of, side)
    for name, (old, _) in sorted(RENAMED[side].items()):
        if name not in REPLICATES[side]:
            parse_name(name, side)
        if not (REPO / name / RESULTS_SENTINEL).is_dir():
            raise FileNotFoundError(
                f"renamed {name} (formerly {old}) has no {REPO / name / RESULTS_SENTINEL}: "
                f"move {old} there first")


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


def cell_source(name, side):
    if name in EXISTING[side]:
        return "existing"
    if name in RENAMED[side]:
        return f"renamed from {RENAMED[side][name][0]}"
    return "generated"


def manifest(side):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["experiment", *BIT_NAMES, "t1_mode", "source"])
    for m, mask in all_cells():
        name = cell_name(m, mask, side)
        w.writerow([name, *levels(m, mask), cell_source(name, side)])
    for name, of in REPLICATES[side].items():
        w.writerow([name, *levels(*parse_name(of, side)), f"replicate of {of}"])
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--side", choices=SIDES, default="a",
                    help="workload: a (expt_a<id>, manifest.csv) or b (expt_b<id>, "
                         "manifest_b.csv)")
    ap.add_argument("--out", type=Path,
                    help="write --cells into this directory instead of the repo")
    ap.add_argument("--cells", help="comma-separated cell ids (with --out only)")
    args = ap.parse_args()
    side = args.side

    check_names(side)

    if args.out:
        if not args.cells:
            ap.error("--out requires --cells")
        for cid in (int(c) for c in args.cells.split(",")):
            m, mask = parse_id(cid)
            write_dir(args.out / cell_name(m, mask, side), cell_files(m, mask, side))
        return
    if args.cells:
        ap.error("--cells requires --out; without --out every generated cell is written")

    for m, mask in all_cells():
        name = cell_name(m, mask, side)
        if name in RENAMED[side]:
            write_dir(REPO / name, {"optimisations.md": renamed_md(name, side)})
        elif name not in EXISTING[side]:
            write_dir(REPO / name, cell_files(m, mask, side))
    for name, of in REPLICATES[side].items():
        if name in RENAMED[side]:
            write_dir(REPO / name, {"optimisations.md": renamed_md(name, side)})
        else:
            write_dir(REPO / name, replicate_files(name, of, side))
    (ABLATION_DIR / MANIFEST[side]).write_text(manifest(side))


if __name__ == "__main__":
    sys.exit(main())
