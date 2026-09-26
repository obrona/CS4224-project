#!/usr/bin/env python3
"""Validation 1-3 for the ablation cells. Run from the repo root."""
import csv
import difflib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path.cwd()
sys.path.insert(0, str(REPO / "ablation"))
import generate as g  # noqa: E402

fail = []


def bad(msg):
    fail.append(msg)
    print("  FAIL:", msg)


# ---------------------------------------------------------------- check 1
TEMPLATE_RUN = (REPO / "ablation/template/run.sh").read_text().split("\n")
# Lines of the native explain step, as they appear in the template.
start = TEMPLATE_RUN.index("#####################  Explain transactions")
end = next(i for i in range(start, len(TEMPLATE_RUN))
           if TEMPLATE_RUN[i].startswith("explain_transactions &>"))
EXPLAIN_LINES = set(TEMPLATE_RUN[start:end + 1]) | {'EXPLAIN_DIR="${SCRIPT_DIR}/explain"', ""}
MDS_DIST = {"END IF;",
            "IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'merchant_daily_sales'::regclass) THEN",
            "PERFORM create_distributed_table('merchant_daily_sales', 'merchant_id', colocate_with => 'merchants');"}


DIST_LINE = re.compile(r"^(END IF;|IF NOT EXISTS \(SELECT 1 FROM pg_dist_partition WHERE logicalrelid = '\w+'::regclass\) THEN|PERFORM create_distributed_table\('\w+', '\w+', colocate_with => '\w+'\);)$")


def classify(removed, added):
    ch = [l for l in removed + added]
    if not removed and all(l in EXPLAIN_LINES for l in added):
        return "native-explain-step"
    nb = [l.strip() for l in ch if l.strip()]
    if nb and all(DIST_LINE.match(l) for l in nb):
        return "distribute-block-reorder"
    if all(not l.strip() or l.strip().startswith(("#", "--")) for l in ch):
        return "comment/blank"
    return "OTHER"


def hunks(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            yield (i1 + 1, i2, j1 + 1, j2), a[i1:i2], b[j1:j2]


print("=== Check 1: generated masks vs renamed cells")
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    masks = sorted(g.RENAMED)
    subprocess.run([sys.executable, "ablation/generate.py", "--out", str(tmp),
                    "--masks", ",".join(map(str, masks))], check=True)
    for mask in masks:
        name = g.RENAMED[mask][0]
        print(f"-- mask {mask}: {name} (was {g.RENAMED[mask][1]})")
        a = (REPO / name / "run.sh").read_text().split("\n")
        b = (tmp / name / "run.sh").read_text().split("\n")
        moved_rem, moved_add = [], []
        for (i1, i2, j1, j2), rem, add in hunks(a, b):
            cat = classify(rem, add)
            print(f"  run.sh hunk renamed {i1}-{i2} / generated {j1}-{j2}: "
                  f"-{len(rem)} +{len(add)} lines -> {cat}")
            if cat == "OTHER":
                bad(f"{name} run.sh unexplained hunk at {i1}")
            if cat == "distribute-block-reorder":
                moved_rem += rem
                moved_add += add
                print("     moved:", sorted(set(re.findall(r"logicalrelid = '(\w+)'", " ".join(rem + add)))))
        if sorted(moved_rem) != sorted(moved_add):
            bad(f"{name}: distribute hunks are not a pure reorder")
        # the distribute order itself, renamed vs generated
        oa = re.findall(r"logicalrelid = '(\w+)'", "\n".join(a))
        ob = re.findall(r"logicalrelid = '(\w+)'", "\n".join(b))
        if oa != ob:
            print(f"     distribute order renamed:  {oa[6:]}")
            print(f"     distribute order generated: {ob[6:]}")
        for kind in ("transactions", "explain"):
            ren = sorted(p.name for p in (REPO / name / kind).glob("*.sql"))
            gen = sorted(p.name for p in (tmp / name / kind).glob("*.sql"))
            if ren != gen:
                bad(f"{name}/{kind} file sets differ: {ren} vs {gen}")
            for f in ren:
                if (REPO / name / kind / f).read_bytes() != (tmp / name / kind / f).read_bytes():
                    bad(f"{name}/{kind}/{f} differs")
            print(f"  {kind}/*.sql: {len(ren)} files byte-identical" if ren == gen else "")

# ---------------------------------------------------------------- check 2
EXTRA = {"order_merchant_map": "t5_routing", "merchant_daily_sales": "t6_rollup",
         "product_merchant_map": "t7_routing"}
BASE = {"merchants", "customers", "products", "inventory", "orders", "order_items"}
SQL_KW = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+(?:public\.)?([a-z_][a-z0-9_]*)", re.I)
CTE_DEF = re.compile(r"(?:^|,|\bWITH)\s*([a-z_][a-z0-9_]*)\s*(?:\([^)]*\))?\s+AS\s+(?:MATERIALIZED\s+)?\(", re.I | re.M)
NOT_TABLES = {"unnest", "generate_series", "set", "input_items"}
DECLARED = re.compile(r"^\s+(v_\w+)\s", re.M)  # plpgsql locals in place_order


def strip_comments(text):
    return "\n".join(re.sub(r"--.*$", "", l) for l in text.split("\n"))


def cell_dirs():
    rows = list(csv.DictReader(open(REPO / "ablation/manifest.csv")))
    return rows


print("\n=== Check 2: per-cell structure (all manifest rows)")
rows = cell_dirs()
if len(rows) != 34:
    bad(f"manifest has {len(rows)} rows, expected 34")
for row in rows:
    name, mask = row["experiment"], int(row["mask"])
    on = g.enabled(mask)
    for col in g.FACTOR_NAMES:
        if int(row[col]) != int(col in on):
            bad(f"{name}: manifest {col}={row[col]} disagrees with mask {mask}")
    d = REPO / name
    run = (d / "run.sh").read_text()
    errs_before = len(fail)
    r = subprocess.run(["bash", "-n", str(d / "run.sh")], capture_output=True, text=True)
    if r.returncode:
        bad(f"{name}: bash -n: {r.stderr.strip()}")
    if "@ablation" in run or "@{" in run:
        bad(f"{name}: marker left in run.sh")
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
    # tables referenced by transactions
    tx = {p.name: p.read_text() for p in (d / "transactions").glob("T*.sql")}
    for fname, text in tx.items():
        body = strip_comments(text)
        ctes = {m.lower() for m in CTE_DEF.findall(body)}
        refs = {m.lower() for m in SQL_KW.findall(body)} - ctes - NOT_TABLES
        refs -= set(DECLARED.findall(body))  # SELECT/RETURNING ... INTO v_x
        refs = {x for x in refs if not x.startswith("pg_")}  # catalogs
        refs = {x for x in refs if not re.search(rf"\b{x}\s*\(", body) or x in created}
        missing = refs - created
        if missing:
            bad(f"{name}/{fname}: references uncreated {sorted(missing)}")
    t1 = strip_comments(tx["T1_place_order.sql"])
    ins_map = bool(re.search(r"INSERT INTO (public\.)?order_merchant_map", t1))
    ins_mds = bool(re.search(r"INSERT INTO (public\.)?merchant_daily_sales", t1))
    if ins_map != ("t5_routing" in on):
        bad(f"{name}: T1 map insert {ins_map} != t5_routing")
    if ins_mds != ("t6_rollup" in on):
        bad(f"{name}: T1 rollup upsert {ins_mds} != t6_rollup")
    fn_block = "t1_function=$(sed -n" in run
    fn_def = "create_distributed_function" in t1 and "\\if 0" in t1
    delegated = "t1_delegation" in on
    if fn_block != delegated or fn_def != delegated:
        bad(f"{name}: function block {fn_block}/definition {fn_def} != t1_delegation")
    if ("\nBEGIN;" in t1) == delegated:
        bad(f"{name}: T1 transaction block presence wrong for delegation={delegated}")
    for fname, t, f in (("T5_update_order_status.sql", "order_merchant_map", "t5_routing"),
                        ("T6_global_sales.sql", "merchant_daily_sales", "t6_rollup"),
                        ("T7_inventory_transfer.sql", "product_merchant_map", "t7_routing")):
        if (t in strip_comments(tx[fname])) != (f in on):
            bad(f"{name}: {fname} uses {t} != {f}")
    iso = re.findall(r"^PG_ISOLATION_LEVEL=\$\{PG_ISOLATION_LEVEL:-(.*)\}$", run, re.M)
    want_iso = '"repeatable read"' if "repeatable_read" in on else "serializable"
    if iso != [want_iso]:
        bad(f"{name}: isolation defaults {iso} != [{want_iso}]")
    generated = row["source"] != "" and not row["source"].startswith("renamed")
    if generated:
        for needle in ("#SBATCH --nodelist=xcnf[1,3-6]", "#SBATCH --mail-user=alice_and_bob@u.nus.edu",
                       "TEAM_ID=${TEAM_ID:-99}", 'WORKLOAD="${WORKLOAD:-A}"',
                       'PGPORT="${PGPORT:-$((10#${TEAM_ID} + 5432))}"',
                       'EXPLAIN_DIR="${SCRIPT_DIR}/explain"',
                       'explain_transactions &>"$JOB_RESULT_DIR/explain.log"'):
            if needle not in run:
                bad(f"{name}: run.sh lacks {needle}")
    status = "ok" if len(fail) == errs_before else "FAIL"
    print(f"  {name:10s} mask {mask:2d} {row['source']:24s} {status}  tables={sorted(want - BASE)}")

# ---------------------------------------------------------------- check 3
print("\n=== Check 3: explained statements appear in the cell's own transaction")


def norm(s):
    return re.sub(r"\s+", " ", strip_comments(s)).strip()


EXPLAIN_RE = re.compile(r"EXPLAIN\s*\([^)]*\)\s*(.*?);\s*$", re.S | re.M)
total = 0
for row in rows:
    name = row["experiment"]
    d = REPO / name
    n_cell = 0
    for ex in sorted((d / "explain").glob("T*.sql")):
        tx = norm((d / "transactions" / ex.name).read_text())
        text = strip_comments(ex.read_text())
        for stmt in EXPLAIN_RE.findall(text):
            s = norm(stmt)
            pos = tx.find(s)
            ok = pos >= 0 and tx[pos + len(s):pos + len(s) + 1] in (";", "\\", " ")
            # a match must end the statement: next token is ';' or '\gset'
            if ok:
                nxt = tx[pos + len(s):].lstrip()[:5]
                ok = nxt.startswith(";") or nxt.startswith("\\gset")
            n_cell += 1
            if not ok:
                bad(f"{name}/explain/{ex.name}: statement not in transaction: {s[:80]}...")
    total += n_cell
    print(f"  {name:10s} {n_cell} explained statements checked")
print(f"  total {total}")

print("\nRESULT:", "FAIL" if fail else "all checks passed", f"({len(fail)} failures)")
sys.exit(1 if fail else 0)
