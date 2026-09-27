# Sourced by this experiment's run.sh after loading the synthetic dataset.
EXPLAIN_DIR="$SCRIPT_DIR"
EXPLAIN_RESULT_DIR="$JOB_RESULT_DIR/explain-results"
mkdir -p "$EXPLAIN_RESULT_DIR/sql"
((NUM_MERCHANTS >= 2)) || fail "EXPLAIN requires at least two merchants"
((NUM_CUSTOMERS >= 1 && NUM_ORDERS >= 1)) || fail "EXPLAIN requires customers and orders"
((NUM_PRODUCTS >= 1 + 4 * NUM_MERCHANTS)) || fail "EXPLAIN requires five products for merchant 1"

# T1 uses nextval() for both inserts; the benchmark creates these before running.
reset_benchmark_sequences_for_explain() {
    psqlx <<'SQL'
CREATE SEQUENCE benchmark_order_id_seq;
CREATE SEQUENCE benchmark_order_item_id_seq;
SELECT setval('benchmark_order_id_seq', (SELECT MAX(order_id) FROM orders));
SELECT setval('benchmark_order_item_id_seq', (SELECT MAX(order_item_id) FROM order_items));
SQL
}
reset_benchmark_sequences_for_explain

python3 "$EXPLAIN_DIR/build_explain_sql.py" "$TX_DIR" "$EXPLAIN_RESULT_DIR/sql"

# Chosen values exercise existing rows and the hot merchant path. A new psql
# session is used per transaction; ROLLBACK in each SQL file preserves the
# generated dataset for the next plan.
explain_vars=(
    -v merchant_id=1 -v customer_id=1 -v item_count=3
    -v product_id=1 -v product_id_1=1
    -v product_id_2="$((1 + NUM_MERCHANTS))"
    -v product_id_3="$((1 + 2 * NUM_MERCHANTS))"
    -v product_id_4="$((1 + 3 * NUM_MERCHANTS))"
    -v product_id_5="$((1 + 4 * NUM_MERCHANTS))"
    -v qty_1=1 -v qty_2=2 -v qty_3=1 -v qty_4=1 -v qty_5=1
    -v inventory_change=1 -v order_id=1 -v source_product_id=1
    -v dest_product_id=2 -v transfer_qty=1 -v new_email_number=1
    -v price_increase=1 -v REPORT_DAYS="$REPORT_DAYS"
)

STATUS_FILE="$EXPLAIN_RESULT_DIR/status.csv"
printf 'transaction,status,psql_exit_code\n' >"$STATUS_FILE"
failed_count=0
for n in {1..9}; do
    file="$EXPLAIN_RESULT_DIR/sql/T${n}.sql"
    log="$EXPLAIN_RESULT_DIR/T${n}.txt"
    if ((n == 1)); then
        info "EXPLAIN plus timed execution T1 -> $log"
    else
        info "EXPLAIN ANALYZE T${n} -> $log"
    fi
    if psqlx "${explain_vars[@]}" -a -f "$file" >"$log" 2>&1; then
        printf 'T%s,ok,0\n' "$n" >>"$STATUS_FILE"
    else
        rc=$?
        printf 'T%s,failed,%s\n' "$n" "$rc" >>"$STATUS_FILE"
        failed_count=$((failed_count + 1))
        info "T${n} failed (psql exit code $rc); see $log"
    fi
    check_server_steps || fail "Cluster health check failed after T${n}"
done

cat > "$EXPLAIN_RESULT_DIR/README.txt" <<EOF2
A7 transaction plans and execution
==================================
T1.txt contains EXPLAIN without ANALYZE and a psql Time line from executing
T1 once. Citus does not support EXPLAIN ANALYZE for its coordinator-side
INSERT ... SELECT. T2.txt through T9.txt contain EXPLAIN ANALYZE output.
sql/T1.sql through sql/T9.sql contain the exact SQL executed.
status.csv records success or failure for every transaction.
Each transaction runs once with representative existing IDs against the A7
synthetic dataset (scale=$SCALE, seed=$DATA_SEED). Changes are rolled back
between transactions. T5 uses the SHIPPED branch; T7 uses product IDs 1 and 2.
EXPLAIN ANALYZE executes writes; T1 is also executed after EXPLAIN.
T1 sequence values advance despite rollback.
EOF2
info "Transaction plans complete: $EXPLAIN_RESULT_DIR ($failed_count failed)"
((failed_count == 0)) || fail "$failed_count transaction plan(s) failed; inspect $STATUS_FILE and T*.txt"
