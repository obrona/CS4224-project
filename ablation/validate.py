#!/usr/bin/env python3
"""Validation for the 2^4 x 3 ablation grid. Run from the repo root after
ablation/generate.py; exits non-zero on any failure.

  1. Existing cells: the generator's run.sh, transactions/ and explain/ for
     expt_a323/a331/a347 equal the existing directories byte-for-byte
     (optimisations.md is hand-written there and excluded).
  2. Every manifest row: levels, no marker, bash -n, factor-level -> template
     file selection, structure of run.sh and the transactions, on-disk code
     equal to the generator's, explained statements present in the cell's own
     transaction.
  3. Cells differing in one binary bit or one step of m differ only in lines
     and files belonging to that factor.
  4. The generator's outputs: 45 generated cells and the replicates, never an
     existing cell; replicates are named expt_a<id>_<k> after their cell.
  5. A directory with slurm-results/ keeps its code: the generator refuses to
     change run.sh, transactions/ or explain/ there, but rewrites
     optimisations.md.
"""
import csv
import difflib
import itertools
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path.cwd()
sys.dont_write_bytecode = True  # no ablation/__pycache__ in the tree
sys.path.insert(0, str(REPO / "ablation"))
import generate as g  # noqa: E402

fail = []


def bad(msg):
    fail.append(msg)
    print("  FAIL:", msg)


def code(d):
    """{relative path: text} of run.sh, transactions/*.sql, explain/*.sql."""
    files = {"run.sh": (d / "run.sh").read_text()}
    for kind in ("transactions", "explain"):
        for p in sorted((d / kind).glob("*.sql")):
            files[f"{kind}/{p.name}"] = p.read_text()
    return files


# ---------------------------------------------------------------- check 1
# Allowed differences between generated output and an existing directory,
# as {cell: {relative path: reason}}. None are expected or allowed.
ALLOWED_DIFFS = {}

print("=== Check 1: generator output vs existing cells")
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    ids = [int(c.removeprefix("expt_a")) for c in sorted(g.EXISTING)]
    subprocess.run([sys.executable, "ablation/generate.py", "--out", str(tmp),
                    "--cells", ",".join(map(str, ids))], check=True)
    for cell in sorted(g.EXISTING):
        have, gen = code(REPO / cell), code(tmp / cell)
        if set(have) != set(gen):
            bad(f"{cell}: file sets differ: {sorted(set(have) ^ set(gen))}")
        diffs = [rel for rel in sorted(set(have) & set(gen)) if have[rel] != gen[rel]]
        for rel in diffs:
            if rel in ALLOWED_DIFFS.get(cell, {}):
                print(f"  {cell}/{rel}: allowed difference: {ALLOWED_DIFFS[cell][rel]}")
                continue
            bad(f"{cell}/{rel}: generated differs from the existing directory")
            for line in difflib.unified_diff(have[rel].split("\n"), gen[rel].split("\n"),
                                             "existing", "generated", n=0, lineterm=""):
                print("     ", line)
        print(f"  {cell}: {len(have)} files, "
              f"{len(have) - len(diffs)} byte-identical")

# ---------------------------------------------------------------- check 2
EXTRA = {"order_merchant_map": "t5_routing", "merchant_daily_sales": "t6_rollup",
         "product_merchant_map": "t7_routing"}
BASE = {"merchants", "customers", "products", "inventory", "orders", "order_items"}
# "FOR UPDATE OF i" is a row lock, not a table reference.
SQL_KW = re.compile(r"\b(?:FROM|JOIN|INTO|(?<!FOR )UPDATE)\s+(?:public\.)?([a-z_][a-z0-9_]*)", re.I)
CTE_DEF = re.compile(r"(?:^|,|\bWITH)\s*([a-z_][a-z0-9_]*)\s*(?:\([^)]*\))?\s+AS\s+(?:MATERIALIZED\s+)?\(", re.I | re.M)
NOT_TABLES = {"unnest", "generate_series", "set", "input_items"}
DECLARED = re.compile(r"^\s+(v_\w+)\s", re.M)  # plpgsql locals in place_order
REFERENCE_CONFIG = ("#SBATCH --nodelist=xcnf[0-2,4,5]", "TEAM_ID=${TEAM_ID:-4}",
                    "\nPGPORT=$((10#${TEAM_ID} + 5432))\n", 'WORKLOAD="${WORKLOAD:-A}"',
                    'EXPLAIN_DIR="${SCRIPT_DIR}/explain"',
                    'explain_transactions &>"$JOB_RESULT_DIR/explain.log"')
MODES = {mode: m for m, (mode, _) in enumerate(g.T1_MODES)}
EXPLAIN_RE = re.compile(r"EXPLAIN\s*\([^)]*\)\s*(.*?);\s*$", re.S | re.M)
# fn_rc's explain plans the function body's locking stock check with psql
# variables in place of the plpgsql parameters, so the statement is not in the
# transaction file verbatim; its FOR UPDATE clause is checked instead.
RC_LOCK_EXPLAIN = "SELECT i.quantity, p.price FROM inventory i JOIN products p"


def strip_comments(text):
    return "\n".join(re.sub(r"--.*$", "", l) for l in text.split("\n"))


def norm(s):
    return re.sub(r"\s+", " ", strip_comments(s)).strip()


def expected_sources(m, on):
    """Template file (relative to template/) and removed steps per transaction,
    written out from the contract independently of generate.variant_source."""
    lvl = {(0, 0): "none", (1, 0): "map", (0, 1): "rollup", (1, 1): "both"}[
        (int("t5_routing" in on), int("t6_rollup" in on))]
    removed = {"none": (6, 7), "map": (6,), "rollup": (7,), "both": ()}[lvl]
    t1_tx = [f"set_{lvl}.sql", "fn_both.sql", "fn_both_rc.sql"][m]
    t1_ex = [f"set_{lvl}.sql", "fn.sql", "fn_rc.sql"][m]
    want = {("transactions", "T1_place_order"): (f"transactions/T1_place_order/{t1_tx}",
                                                 removed if m else ()),
            ("explain", "T1_place_order"): (f"explain/T1_place_order/{t1_ex}", ())}
    for tx, f in (("T5_update_order_status", "t5_routing"), ("T6_global_sales", "t6_rollup"),
                  ("T7_inventory_transfer", "t7_routing")):
        for kind in ("transactions", "explain"):
            want[(kind, tx)] = (f"{kind}/{tx}/{'on' if f in on else 'off'}.sql", ())
    for tx in ("T2_update_inventory", "T3_order_history", "T4_product_lookup",
               "T8_update_customer", "T9_update_product"):
        for kind in ("transactions", "explain"):
            want[(kind, tx)] = (f"{kind}/{tx}.sql", ())
    return want


print("\n=== Check 2: per-cell structure (all manifest rows)")
rows = list(csv.DictReader(open(REPO / "ablation/manifest.csv")))
if [list(rows[0])] != [["experiment", *g.BIT_NAMES, "t1_mode", "source"]]:
    bad(f"manifest columns {list(rows[0])}")
names = [r["experiment"] for r in rows]
want_names = [f"expt_a{i}" for i in range(300, 348)] + ["expt_a300_1", "expt_a331_1"]
if names != want_names:
    bad(f"manifest rows {names} != expt_a300..a347, expt_a300_1, expt_a331_1")
counts = {k: sum(r["source"].startswith(k) for r in rows)
          for k in ("generated", "existing", "replicate")}
print(f"  manifest: {len(rows)} rows: {counts}")
if counts != {"generated": 45, "existing": 3, "replicate": 2}:
    bad(f"manifest source counts {counts}")

for row in rows:
    name = row["experiment"]
    if row["source"].startswith("replicate of "):
        of = row["source"].removeprefix("replicate of ")
        m, mask = g.parse_id(int(of.removeprefix("expt_a")))
    else:
        m, mask = g.parse_id(int(name.removeprefix("expt_a")))
    on = g.enabled(m, mask)
    errs_before = len(fail)
    for value, col, _ in g.BITS:
        if row[col] != str(int(bool(mask & value))):
            bad(f"{name}: manifest {col}={row[col]} disagrees with mask {mask}")
    if MODES.get(row["t1_mode"]) != m:
        bad(f"{name}: manifest t1_mode={row['t1_mode']} disagrees with m={m}")
    want_source = ("existing" if name in g.EXISTING
                   else row["source"] if name in g.REPLICATES else "generated")
    if row["source"] != want_source or (name in g.REPLICATES and of != g.REPLICATES[name]):
        bad(f"{name}: source {row['source']!r}")
    d = REPO / name
    files = code(d)
    run = files["run.sh"]

    # on-disk code is the generator's (generated, replicate) or the source's
    if name in g.EXISTING:
        pass  # check 1
    elif name in g.REPLICATES:
        src = code(REPO / of)
        if files != src:
            bad(f"{name}: code differs from {of}: "
                f"{sorted(k for k in set(files) | set(src) if files.get(k) != src.get(k))}")
    else:
        gen = g.cell_files(m, mask)
        stale = sorted(k for k in gen if not (d / k).exists() or (d / k).read_text() != gen[k])
        if stale:
            bad(f"{name}: on disk differs from generator (regenerate): {stale}")
        # factor level -> template file selection
        for (kind, tx), (rel, removed) in expected_sources(m, on).items():
            path, got_removed = g.variant_source(kind, tx, on)
            if str(path.relative_to(g.TEMPLATE)) != rel or tuple(got_removed) != removed:
                bad(f"{name}: {kind}/{tx} from {path.relative_to(g.TEMPLATE)} "
                    f"minus steps {got_removed}, expected {rel} minus {removed}")

    r = subprocess.run(["bash", "-n", str(d / "run.sh")], capture_output=True, text=True)
    if r.returncode:
        bad(f"{name}: bash -n: {r.stderr.strip()}")
    if any("@ablation" in t or "@{" in t for t in files.values()):
        bad(f"{name}: marker left in output")
    for needle in REFERENCE_CONFIG:
        if needle not in run:
            bad(f"{name}: run.sh lacks {needle.strip()}")

    # tables
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", run))
    dropped = set(re.findall(r"DROP TABLE IF EXISTS (\w+)", run))
    distributed = set(re.findall(r"logicalrelid = '(\w+)'::regclass", run))
    tr = re.findall(r"TRUNCATE TABLE ([\w,]+) CASCADE", run)
    truncated = set(tr[0].split(",")) if len(tr) == 1 else None
    want = BASE | {t for t, f in EXTRA.items() if f in on}
    for label, s in (("created", created), ("dropped", dropped),
                     ("distributed", distributed), ("truncated", truncated)):
        if s != want:
            bad(f"{name}: {label} tables {sorted(s) if s else s} != {sorted(want)}")
    for t in want - BASE:
        if not re.search(rf"^INSERT INTO {t} \(", run, re.M):
            bad(f"{name}: {t} created but not filled")
    if ("idx_mds_period" in run) != ("t6_rollup" in on):
        bad(f"{name}: idx_mds_period presence != t6_rollup")

    # shards8
    shard_lines = re.findall(r"^.*(?:CITUS_SHARD_COUNT|citus\.shard_count).*$", run, re.M)
    want_shard = ['CITUS_SHARD_COUNT="${CITUS_SHARD_COUNT:-8}"',
                  '\tpsqlx -v shard_count="$CITUS_SHARD_COUNT" <<\'SQL\'',
                  'SET citus.shard_count = :shard_count;',
                  'CITUS_SHARD_COUNT="${CITUS_SHARD_COUNT}"']
    if shard_lines != (want_shard if "shards8" in on else []):
        bad(f"{name}: shard-count lines {shard_lines} wrong for shards8={'shards8' in on}")

    # isolation, rc lock
    iso = re.findall(r"^PG_ISOLATION_LEVEL=.*:-.*$", run, re.M)
    want_iso = ('PG_ISOLATION_LEVEL="${PG_ISOLATION_LEVEL:-read committed}"' if m == 2
                else "PG_ISOLATION_LEVEL=${PG_ISOLATION_LEVEL:-serializable}")
    if iso != [want_iso]:
        bad(f"{name}: isolation default {iso} != [{want_iso}]")

    # transactions reference only created tables
    for rel, text in files.items():
        if not rel.startswith("transactions/"):
            continue
        body = strip_comments(text)
        ctes = {x.lower() for x in CTE_DEF.findall(body)}
        refs = {x.lower() for x in SQL_KW.findall(body)} - ctes - NOT_TABLES
        refs -= set(DECLARED.findall(body))  # SELECT/RETURNING ... INTO v_x
        refs = {x for x in refs if not x.startswith("pg_")}  # catalogs
        refs = {x for x in refs if not re.search(rf"\b{x}\s*\(", body) or x in created}
        if refs - created:
            bad(f"{name}/{rel}: references uncreated {sorted(refs - created)}")

    # T1 by level
    t1 = strip_comments(files["transactions/T1_place_order.sql"])
    if bool(re.search(r"INSERT INTO (public\.)?order_merchant_map", t1)) != ("t5_routing" in on):
        bad(f"{name}: T1 map insert != t5_routing")
    if bool(re.search(r"INSERT INTO (public\.)?merchant_daily_sales", t1)) != ("t6_rollup" in on):
        bad(f"{name}: T1 rollup upsert != t6_rollup")
    delegated = m >= 1
    fn_block = "t1_function=$(sed -n" in run
    fn_def = "create_distributed_function" in t1 and "\\if 0" in t1
    if fn_block != delegated or fn_def != delegated:
        bad(f"{name}: function block {fn_block}/definition {fn_def} != m>=1")
    if ("\nBEGIN;" in t1) == delegated:
        bad(f"{name}: T1 transaction block presence wrong for m={m}")
    if ("FOR UPDATE OF i;" in t1) != (m == 2) or \
            ("SET plan_cache_mode = force_custom_plan" in t1) != (m == 2):
        bad(f"{name}: T1 stock lock / plan_cache_mode presence wrong for m={m}")
    for rel, t, f in (("transactions/T5_update_order_status.sql", "order_merchant_map", "t5_routing"),
                      ("transactions/T6_global_sales.sql", "merchant_daily_sales", "t6_rollup"),
                      ("transactions/T7_inventory_transfer.sql", "product_merchant_map", "t7_routing")):
        if (t in strip_comments(files[rel])) != (f in on):
            bad(f"{name}: {rel} uses {t} != {f}")

    # explained statements appear in the cell's own transaction
    n_explained = 0
    for rel, text in files.items():
        if not rel.startswith("explain/"):
            continue
        tx = norm(files["transactions/" + rel.removeprefix("explain/")])
        for stmt in EXPLAIN_RE.findall(strip_comments(text)):
            s = norm(stmt)
            n_explained += 1
            if m == 2 and rel == "explain/T1_place_order.sql" and s.startswith(RC_LOCK_EXPLAIN):
                if not s.endswith("FOR UPDATE OF i") or "FOR UPDATE OF i;" not in tx:
                    bad(f"{name}/{rel}: rc lock-check explain does not match T1")
                continue
            pos = tx.find(s)
            nxt = tx[pos + len(s):].lstrip()[:5] if pos >= 0 else ""
            if not (nxt.startswith(";") or nxt.startswith("\\gset")):
                bad(f"{name}/{rel}: statement not in transaction: {s[:80]}...")
    status = "ok" if len(fail) == errs_before else "FAIL"
    print(f"  {name:10s} m={m} mask={mask:2d} {row['source']:24s} "
          f"explained={n_explained} {status}")

# ---------------------------------------------------------------- check 3
print("\n=== Check 3: one-factor neighbours differ only in that factor")
# Lines of template/run.sh each factor controls: lines inside its blocks, and
# every rendering of a line with an inline marker for it.
template = (g.TEMPLATE / "run.sh").read_text().split("\n")
owned_lines = {f: set() for f in g.TEMPLATE_FACTORS}
block = None
for line in template:
    b, e = g.MARKER_BEGIN.match(line), g.MARKER_END.match(line)
    if b:
        block = b.group(2)
    elif e:
        block = None
    elif block:
        owned_lines[block].add(line)
    else:
        inl = sorted({x[1] for x in g.INLINE.findall(line)})
        for bits in itertools.product((False, True), repeat=len(inl)):
            on = {f for f, b2 in zip(inl, bits) if b2}
            text = g.render(line, on, "inline")
            for f in inl:
                owned_lines[f].add(text)
OWNED_FILES = {
    "t5_routing": {"T1_place_order", "T5_update_order_status"},
    "t6_rollup": {"T1_place_order", "T6_global_sales"},
    "t7_routing": {"T7_inventory_transfer"},
    "shards8": set(),
    "t1_delegation": {"T1_place_order"},
    "rc_lock": {"T1_place_order"},
}
pairs = []
for m, mask in g.all_cells():
    for value, f, _ in g.BITS:
        if not mask & value:
            pairs.append(((m, mask), (m, mask | value), f))
    if m + 1 < len(g.T1_MODES):
        pairs.append(((m, mask), (m + 1, mask), ["t1_delegation", "rc_lock"][m]))
per_factor = {}
for a, b, f in pairs:
    na, nb = g.cell_name(*a), g.cell_name(*b)
    ca, cb = code(REPO / na), code(REPO / nb)
    sm = difflib.SequenceMatcher(None, ca["run.sh"].split("\n"), cb["run.sh"].split("\n"),
                                 autojunk=False)
    changed = [l for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"
               for l in ca["run.sh"].split("\n")[i1:i2] + cb["run.sh"].split("\n")[j1:j2]]
    foreign = [l for l in changed if l not in owned_lines[f]]
    if not changed:
        bad(f"{na} -> {nb} ({f}): run.sh identical")
    if foreign:
        bad(f"{na} -> {nb} ({f}): run.sh lines not owned by {f}: {foreign[:3]}")
    diff_files = {k for k in set(ca) | set(cb) if k != "run.sh" and ca.get(k) != cb.get(k)}
    stray = {k for k in diff_files if Path(k).stem not in OWNED_FILES[f]}
    if stray:
        bad(f"{na} -> {nb} ({f}): files outside {f}: {sorted(stray)}")
    if bool(diff_files) != bool(OWNED_FILES[f]):
        bad(f"{na} -> {nb} ({f}): changed files {sorted(diff_files)}")
    st = per_factor.setdefault(f, [0, set()])
    st[0] += 1
    st[1].add(len(changed))
for f, (n, sizes) in per_factor.items():
    print(f"  {f:14s} {n:3d} pairs, changed run.sh lines per pair: {sorted(sizes)}")
print(f"  total {len(pairs)} pairs")

# ---------------------------------------------------------------- check 4
print("\n=== Check 4: generator outputs and replicate names")
outs = g.outputs()
print(f"  generator outputs: {len(outs)} "
      f"({len([o for o in outs if o not in g.REPLICATES])} cells + {len(g.REPLICATES)} replicates)")
if len(outs) != 47 or len(set(outs)) != 47:
    bad(f"expected 45 generated cells + 2 replicates, got {len(outs)}")
if set(outs) & g.EXISTING:
    bad(f"outputs include existing cells: {sorted(set(outs) & g.EXISTING)}")
try:
    g.check_names()
except (ValueError, FileNotFoundError) as e:
    bad(f"names: {e}")

# ---------------------------------------------------------------- check 5
print("\n=== Check 5: a directory with slurm-results/ keeps its code")
with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp) / "expt_a300"
    files = g.cell_files(0, 0)
    g.write_dir(d, files)
    (d / g.RESULTS_SENTINEL).mkdir()
    docs = dict(files, **{"optimisations.md": files["optimisations.md"] + "edited\n"})
    try:
        g.write_dir(d, docs)
    except RuntimeError as e:
        bad(f"docs-only rewrite of a run directory refused: {e}")
    if (d / "optimisations.md").read_text() != docs["optimisations.md"]:
        bad("docs-only rewrite of a run directory did not write optimisations.md")
    else:
        print("  optimisations.md rewritten in a directory with slurm-results/")
    for rel in ("run.sh", "transactions/T1_place_order.sql", "explain/T6_global_sales.sql"):
        changed = dict(docs, **{rel: files[rel] + "-- changed\n"})
        try:
            g.write_dir(d, changed)
        except RuntimeError:
            if code(d) != {k: v for k, v in files.items() if k != "optimisations.md"}:
                bad(f"refused change to {rel} but the directory's code changed anyway")
            else:
                print(f"  change to {rel} refused, code untouched")
        else:
            bad(f"write_dir changed {rel} in a directory with slurm-results/")

print("\nRESULT:", "FAIL" if fail else "all checks passed", f"({len(fail)} failures)")
sys.exit(1 if fail else 0)
