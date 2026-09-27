#!/usr/bin/env bash
#SBATCH --job-name=citus-project
#SBATCH --nodes=5
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --output=citus-%j.out
#SBATCH --error=citus-%j.err
#SBATCH --partition=normal
#SBATCH --time=03:00:00
#SBATCH --mail-type=BEGIN,END,FAIL
# don't run on nodes with arm processor / ubuntu 26.04
# temporarily exclude xcnc13 as server is problematic
#SBATCH --exclude=xcng0,xcng1,xgpj0,xcnh[0-3],xcnc13

# IMPORTANT - replace this with your email
#SBATCH --mail-user=alice_and_bob@u.nus.edu

set -euo pipefail

# IMPORTANT: replace 99 with your project team number (e.g., 1, 2, ..., 20) to ensure a unique PGPORT number for each team
TEAM_ID=${TEAM_ID:-99}

################# PostgreSQL environment variables
PGPORT=$((10#${TEAM_ID} + 5432))
PGUSER="${SLURM_JOB_USER:-${USER}}"

DATA_ROOT=/tmp/${PGUSER}/citus-${SLURM_JOB_ID}
PGDATA="${DATA_ROOT}/pgdata"

PGDATABASE="project-${SLURM_JOB_ID}"

################# Directories
INSTALL_DIR=$HOME/pgsql
PG_BIN_DIR="${INSTALL_DIR}/bin"

RESULT_ROOT="${RESULT_ROOT:-${SLURM_SUBMIT_DIR}/slurm-results}"
JOB_RESULT_DIR="${RESULT_ROOT}/job-${SLURM_JOB_ID}"
RUN_DIR="${JOB_RESULT_DIR}/explain-results"
LOG_DIR="${RUN_DIR}/logs"

SCRIPT_DIR="${SCRIPT_DIR:-${SLURM_SUBMIT_DIR}}"
TX_DIR="${SCRIPT_DIR}/transactions"

################# Files
EXPLAIN_LOG_FILE="${JOB_RESULT_DIR}/explain.log"

SUMMARY_FILE="${RUN_DIR}/summary.csv"
TX_METRICS_FILE="${RUN_DIR}/transaction_metrics.csv"
BENCHMARK_CONFIG_FILE="${RUN_DIR}/config.txt"
README_METRICS_FILE="${RUN_DIR}/README-metrics.txt"

PSQL="${PG_BIN_DIR}/psql"
PGBENCH="${PG_BIN_DIR}/pgbench"

################# PostgreSQL configuration
PG_SHARED_BUFFERS="${PG_SHARED_BUFFERS:-1GB}"
PG_WORK_MEM="${PG_WORK_MEM:-32MB}"
PG_MAINTENANCE_WORK_MEM="${PG_MAINTENANCE_WORK_MEM:-256MB}"
PG_MAX_CONNECTIONS="${PG_MAX_CONNECTIONS:-1000}"
PG_ISOLATION_LEVEL=${PG_ISOLATION_LEVEL:-"repeatable read"}

PG_MAX_WAL_SIZE="${PG_MAX_WAL_SIZE:-16GB}"
PG_MIN_WAL_SIZE="${PG_MIN_WAL_SIZE:-2GB}"
PG_CHECKPOINT_TIMEOUT="${PG_CHECKPOINT_TIMEOUT:-30min}"
PG_CHECKPOINT_COMPLETION_TARGET="${PG_CHECKPOINT_COMPLETION_TARGET:-0.9}"

################# Citus configuration
CITUS_ENABLE_REPARTITION_JOINS="${CITUS_ENABLE_REPARTITION_JOINS:-on}"
CITUS_MAX_SHARED_POOL_SIZE="${CITUS_MAX_SHARED_POOL_SIZE:-300}"
CITUS_MAX_ADAPTIVE_EXECUTOR_POOL_SIZE="${CITUS_MAX_ADAPTIVE_EXECUTOR_POOL_SIZE:-4}"
CITUS_LOCAL_SHARED_POOL_SIZE="${CITUS_LOCAL_SHARED_POOL_SIZE:-150}"

################# Data generation configuration
SCALE="${SCALE:-1}"          # scaling factor
DATA_SEED="${DATA_SEED:-42}" # seed for data generation
HOT_MERCHANT_PERCENT="${HOT_MERCHANT_PERCENT:-10}"
HOT_ORDER_PERCENT="${HOT_ORDER_PERCENT:-50}"

################# Benchmarking configuration
PGBENCH_SEED="${PGBENCH_SEED:-42}"
PGBENCH_MAX_TRIES="${PGBENCH_MAX_TRIES:-3}"
PGBENCH_FAILURES_DETAILED="${PGBENCH_FAILURES_DETAILED:-1}"
PGBENCH_QUERY_MODE="${PGBENCH_QUERY_MODE:-simple}"

CLIENT_COUNTS="${CLIENT_COUNTS:-1 4 8 16 32 64}"
THREADS="${THREADS:-${SLURM_CPUS_PER_TASK:-4}}"

DURATION="${DURATION:-600}"              # 10 minutes (short duration for testing)
WARMUP_DURATION="${WARMUP_DURATION:-60}" # 1 minute

PROGRESS_INTERVAL="${PROGRESS_INTERVAL:-10}"
LOG_SAMPLE_RATE="${LOG_SAMPLE_RATE:-1.0}" # must not change this value

RESET_BETWEEN_CLIENT_COUNTS="${RESET_BETWEEN_CLIENT_COUNTS:-1}"
RESET_AFTER_WARMUP="${RESET_AFTER_WARMUP:-0}"
RESTART_SERVERS_BETWEEN_CLIENT_COUNTS="${RESTART_SERVERS_BETWEEN_CLIENT_COUNTS:-1}"
SERVER_RESTART_TIMEOUT="${SERVER_RESTART_TIMEOUT:-60}"

# Weights for transaction workloads A & B
WORKLOAD="${WORKLOAD:-A}"
if [[ "${WORKLOAD}" == "A" ]]; then
	# Transaction weights for workload A
	T1_WEIGHT="${T1_WEIGHT:-36}"
	T2_WEIGHT="${T2_WEIGHT:-20}"
	T3_WEIGHT="${T3_WEIGHT:-10}"
	T4_WEIGHT="${T4_WEIGHT:-10}"
	T5_WEIGHT="${T5_WEIGHT:-10}"
	T6_WEIGHT="${T6_WEIGHT:-5}"
	T7_WEIGHT="${T7_WEIGHT:-5}"
	T8_WEIGHT="${T8_WEIGHT:-2}"
	T9_WEIGHT="${T9_WEIGHT:-2}"
elif [[ "${WORKLOAD}" == "B" ]]; then
	# Transaction weights for workload B
	T1_WEIGHT="${T1_WEIGHT:-10}"
	T2_WEIGHT="${T2_WEIGHT:-10}"
	T3_WEIGHT="${T3_WEIGHT:-5}"
	T4_WEIGHT="${T4_WEIGHT:-5}"
	T5_WEIGHT="${T5_WEIGHT:-10}"
	T6_WEIGHT="${T6_WEIGHT:-10}"
	T7_WEIGHT="${T7_WEIGHT:-30}"
	T8_WEIGHT="${T8_WEIGHT:-10}"
	T9_WEIGHT="${T9_WEIGHT:-10}"
else
	echo "Invalid workload ${WORKLOAD}" >&2
	exit 1
fi

# Transaction T1
MIN_ITEMS_PER_ORDER="${MIN_ITEMS_PER_ORDER:-1}"
MAX_ITEMS_PER_ORDER="${MAX_ITEMS_PER_ORDER:-5}"
MIN_ORDER_QTY="${MIN_ORDER_QTY:-1}"
MAX_ORDER_QTY="${MAX_ORDER_QTY:-5}"

# Transaction T2
INVENTORY_CHANGE_MIN="${INVENTORY_CHANGE_MIN:--5}"
INVENTORY_CHANGE_MAX="${INVENTORY_CHANGE_MAX:-20}"

# Transaction T6
REPORT_DAYS="${REPORT_DAYS:-30}"

# Transaction T7
T7_MIN_TRANSFER_QTY="${T7_MIN_TRANSFER_QTY:-1}"
T7_MAX_TRANSFER_QTY="${T7_MAX_TRANSFER_QTY:-5}"

################# Script initialization
CLEANUP_STARTED=0  # clean up has not started
SERVERS_LAUNCHED=0 # servers have not been launched
declare -a SERVER_PIDS=()
declare -a NODES=()

############### Functions

info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

fail() {
	echo "ERROR: $*" >&2
	exit 1
}

psqlx() { ${PSQL} -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"; }

### clean up on exit
cleanup() {
	local exit_code=$?

	# Prevent cleanup from running twice, e.g. TERM followed by EXIT.
	if ((CLEANUP_STARTED)); then
		return
	fi
	CLEANUP_STARTED=1

	set +e

	if ((exit_code == 0)); then
		echo "Running cleanup after successful completion..."
	else
		echo "Running cleanup after failure; exit code=$exit_code"
	fi

	if ((SERVERS_LAUNCHED)); then
		local n
		for n in "${NODES[@]:-}"; do
			srun \
				--overlap \
				--exact \
				--nodes=1 \
				--ntasks=1 \
				--cpus-per-task=1 \
				--nodelist="$n" \
				bash -c \
				"${PG_BIN_DIR}/pg_ctl -D '${PGDATA}' stop -m fast \
		 >/dev/null 2>&1 || true" ||
				true
		done
		bounded_wait_server_pids || true
	fi
	return "$exit_code"
}

### reap srun processes
bounded_wait_server_pids() {
	local timeout_seconds="${SERVER_WAIT_TIMEOUT:-30}"
	local elapsed=0
	local p
	local any_alive

	while ((elapsed < timeout_seconds)); do
		any_alive=0

		for p in "${SERVER_PIDS[@]:-}"; do
			if kill -0 "$p" 2>/dev/null; then
				any_alive=1
				break
			fi
		done

		((any_alive == 0)) && break

		sleep 1
		elapsed=$((elapsed + 1))
	done

	for p in "${SERVER_PIDS[@]:-}"; do
		if kill -0 "$p" 2>/dev/null; then
			kill "$p" 2>/dev/null || true
		fi
	done

	for p in "${SERVER_PIDS[@]:-}"; do
		wait "$p" 2>/dev/null || true
	done
}

### check for any PostgreSQL server failure
check_server_steps() {
	local p
	local n

	# Check the local Slurm server steps.
	for p in "${SERVER_PIDS[@]:-}"; do
		if ! kill -0 "$p" 2>/dev/null; then
			echo "ERROR: PostgreSQL server srun step terminated unexpectedly" >&2
			return 1
		fi
	done

	# Check PostgreSQL connectivity to every allocated node.
	for n in "${NODES[@]:-}"; do
		if ! "${PG_BIN_DIR}/pg_isready" \
			-h "$n" \
			-p "$PGPORT" \
			-U "$PGUSER" \
			-d postgres \
			>/dev/null 2>&1; then
			echo "ERROR: PostgreSQL is unavailable on $n:$PGPORT" >&2
			return 1
		fi
	done
}

### initialize database cluster at node specified by first parameter value
init_node() {
	local n="$1"
	srun --overlap --exact --nodes=1 --ntasks=1 --cpus-per-task=1 --nodelist="$n" bash -s <<EOF2
set -euo pipefail

if [ -d "${DATA_ROOT}" ]; then rm -rf "$DATA_ROOT"; fi 
mkdir -p "$PGDATA" "$DATA_ROOT"

${PG_BIN_DIR}/initdb -D "$PGDATA" --username="$PGUSER" --auth=trust --encoding=UTF8 --locale=C
cat >> "$PGDATA/postgresql.conf" <<CONF
listen_addresses='*'
port=$PGPORT
shared_preload_libraries='citus'
max_connections=$PG_MAX_CONNECTIONS
shared_buffers='$PG_SHARED_BUFFERS'
work_mem='$PG_WORK_MEM'
maintenance_work_mem='$PG_MAINTENANCE_WORK_MEM'
default_transaction_isolation='$PG_ISOLATION_LEVEL'
max_wal_size='$PG_MAX_WAL_SIZE'
min_wal_size='$PG_MIN_WAL_SIZE'
checkpoint_timeout='$PG_CHECKPOINT_TIMEOUT'
checkpoint_completion_target=$PG_CHECKPOINT_COMPLETION_TARGET
citus.enable_repartition_joins=$CITUS_ENABLE_REPARTITION_JOINS
citus.max_shared_pool_size=$CITUS_MAX_SHARED_POOL_SIZE
citus.max_adaptive_executor_pool_size=$CITUS_MAX_ADAPTIVE_EXECUTOR_POOL_SIZE
citus.local_shared_pool_size=$CITUS_LOCAL_SHARED_POOL_SIZE
CONF
cat >> "$PGDATA/pg_hba.conf" <<HBA
host all all 0.0.0.0/0 trust
host all all ::/0 trust
HBA
EOF2
}

### record PostgreSQL/Citus versions
record_server_versions() {
	{
		echo "PostgreSQL:"
		${PSQL} -X -A -t \
			-h "$COORDINATOR" \
			-p "$PGPORT" \
			-U "$PGUSER" \
			-d "$PGDATABASE" \
			-c "SELECT version();" || true

		echo
		echo "Citus:"
		${PSQL} -X -A -t \
			-h "$COORDINATOR" \
			-p "$PGPORT" \
			-U "$PGUSER" \
			-d "$PGDATABASE" \
			-c "SELECT citus_version();" || true
	} >"$JOB_RESULT_DIR/server_versions.log" 2>&1
}

##################################### Start server at each node

trap cleanup EXIT INT TERM

info "Slurm job started"
info "SLURM_JOB_ID=${SLURM_JOB_ID:-UNSET}"
info "SLURM_JOB_NODELIST=${SLURM_JOB_NODELIST:-UNSET}"
info "SLURM_CPUS_PER_TASK=${SLURM_CPUS_PER_TASK:-UNSET}"
info "SLURM_SUBMIT_DIR=${SLURM_SUBMIT_DIR:-UNSET}"
info "PG_BIN_DIR=$PG_BIN_DIR"

[[ -n "${SLURM_JOB_ID:-}" ]] || fail "Run with sbatch or inside a Slurm allocation"

for b in srun scontrol; do command -v "$b" >/dev/null 2>&1 || fail "$b not found"; done
for b in awk sort; do command -v "$b" >/dev/null 2>&1 || fail "$b not found"; done
for b in postgres initdb pg_ctl pg_isready psql createdb pgbench; do
	[[ -x "${PG_BIN_DIR}/$b" ]] ||
		fail "${PG_BIN_DIR}/$b not found or not executable"
done

info "Startup validation passed"

mkdir -p "${JOB_RESULT_DIR}"

# record coordinator & worker nodes
mapfile -t NODES < <(scontrol show hostnames "$SLURM_JOB_NODELIST")
((${#NODES[@]} >= 2)) || fail "Need at least 2 nodes: coordinator + worker"
COORDINATOR="${NODES[0]}"
WORKERS=("${NODES[@]:1}")
{
	echo "coordinator=$COORDINATOR"
	i=1
	for w in "${WORKERS[@]}"; do
		echo "worker_${i}=$w"
		i=$((i + 1))
	done
} >"$JOB_RESULT_DIR/topology.txt"

info "Checking that commands can be launched on every allocated node"
for n in "${NODES[@]}"; do
	info "Checking node $n"

	if ! srun \
		--overlap \
		--exact \
		--nodes=1 \
		--ntasks=1 \
		--cpus-per-task=1 \
		--nodelist="$n" \
		hostname; then
		fail "Unable to launch a Slurm job step on node $n"
	fi
done
info "All allocated nodes passed Slurm launch test"

# initialize database cluster at each server
for n in "${NODES[@]}"; do init_node "$n"; done

# start postgres server at each node
# SERVER_PIDS = srun process ids
for n in "${NODES[@]}"; do
	PG_LOGFILE="${JOB_RESULT_DIR}/$n-postgresql.log"
	srun --overlap --nodes=1 --ntasks=1 --nodelist="$n" bash -c "exec ${PG_BIN_DIR}/postgres -D '${PGDATA}' > '${PG_LOGFILE}' 2>&1" &
	SERVER_PIDS+=("$!")
done
SERVERS_LAUNCHED=1 # servers launched

# create database at each server
for n in "${NODES[@]}"; do
	ready=0
	for _ in $(seq 1 60); do
		if "${PG_BIN_DIR}/pg_isready" -h "$n" -p "$PGPORT" -U "$PGUSER" -d postgres >/dev/null 2>&1; then
			ready=1
			break
		fi
		sleep 1
	done
	((ready == 1)) || fail "PostgreSQL failed on $n"
	${PG_BIN_DIR}/createdb -h "$n" -p "$PGPORT" -U "$PGUSER" "$PGDATABASE"
	${PSQL} -X -v ON_ERROR_STOP=1 -h "$n" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -c "CREATE EXTENSION IF NOT EXISTS citus;"
done

# register each worker node at coordinator
for w in "${WORKERS[@]}"; do
	${PSQL} -X -v ON_ERROR_STOP=1 -h "$COORDINATOR" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -c "SELECT * FROM citus_add_node('$w',$PGPORT);"
done

record_server_versions || true

############### Functions: create database schema

### create schema
create_schema() {
	DROP_EXISTING=1
	CREATE_CITUS_EXTENSION=0

	[[ "$CREATE_CITUS_EXTENSION" == "1" ]] && psqlx -c "CREATE EXTENSION IF NOT EXISTS citus;"

	if [[ "$DROP_EXISTING" == "1" ]]; then
		psqlx <<'SQL'
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS order_route CASCADE;
DROP TABLE IF EXISTS product_route CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS inventory CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS merchants CASCADE;
SQL
	fi

	psqlx <<'SQL'
CREATE TABLE IF NOT EXISTS merchants (
	merchant_id BIGINT PRIMARY KEY,
	merchant_name TEXT NOT NULL,
	region TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
	customer_id BIGINT NOT NULL,
	merchant_id BIGINT NOT NULL,
	customer_name TEXT NOT NULL,
	email TEXT NOT NULL,
	created_at TIMESTAMP NOT NULL,
	PRIMARY KEY (merchant_id, customer_id)
);

CREATE TABLE IF NOT EXISTS products (
	product_id BIGINT NOT NULL,
	merchant_id BIGINT NOT NULL,
	product_name TEXT NOT NULL,
	category TEXT,
	price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
	PRIMARY KEY (merchant_id, product_id)
);

CREATE TABLE IF NOT EXISTS inventory (
	inventory_id BIGINT NOT NULL,
	merchant_id BIGINT NOT NULL,
	product_id BIGINT NOT NULL,
	quantity INTEGER NOT NULL CHECK (quantity >= 0),
	updated_at TIMESTAMP NOT NULL,
	PRIMARY KEY (merchant_id, inventory_id),
	UNIQUE (merchant_id, product_id)
) WITH (fillfactor = 80);

CREATE TABLE IF NOT EXISTS orders (
	order_id BIGINT NOT NULL,
	merchant_id BIGINT NOT NULL,
	customer_id BIGINT NOT NULL,
	order_status TEXT NOT NULL,
	total_amount NUMERIC(12, 2) NOT NULL CHECK (total_amount >= 0),
	created_at TIMESTAMP NOT NULL,
	PRIMARY KEY (merchant_id, order_id)
) WITH (fillfactor = 85);

CREATE TABLE IF NOT EXISTS order_items (
	order_item_id BIGINT NOT NULL,
	merchant_id BIGINT NOT NULL,
	order_id BIGINT NOT NULL,
	product_id BIGINT NOT NULL,
	quantity INTEGER NOT NULL CHECK (quantity > 0),
	unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
	PRIMARY KEY (merchant_id, order_item_id)
);

CREATE TABLE IF NOT EXISTS order_route (
	order_id BIGINT PRIMARY KEY,
	merchant_id BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_route (
	product_id BIGINT PRIMARY KEY,
	inventory_id BIGINT NOT NULL,
	merchant_id BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_customer_recent
	ON orders (merchant_id, customer_id, created_at DESC, order_id);

CREATE INDEX IF NOT EXISTS idx_order_items_order
	ON order_items (merchant_id, order_id);

CREATE INDEX IF NOT EXISTS idx_orders_sales_period
	ON orders (created_at)
	INCLUDE (merchant_id, total_amount);
SQL

	psqlx <<'SQL'
DO $$
BEGIN
	IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
		IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'merchants'::regclass) THEN
			PERFORM create_distributed_table('merchants', 'merchant_id');
		END IF;

		IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'customers'::regclass) THEN
			PERFORM create_distributed_table('customers', 'merchant_id', colocate_with => 'merchants');
		END IF;

		IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'products'::regclass) THEN
			PERFORM create_distributed_table('products', 'merchant_id', colocate_with => 'merchants');
		END IF;

		IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'inventory'::regclass) THEN
			PERFORM create_distributed_table('inventory', 'merchant_id', colocate_with => 'merchants');
		END IF;

		IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'orders'::regclass) THEN
			PERFORM create_distributed_table('orders', 'merchant_id', colocate_with => 'merchants');
		END IF;

		IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'order_items'::regclass) THEN
			PERFORM create_distributed_table('order_items', 'merchant_id', colocate_with => 'merchants');
		END IF;
		IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'order_route'::regclass) THEN
			PERFORM create_distributed_table('order_route', 'order_id');
		END IF;
		IF NOT EXISTS (SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'product_route'::regclass) THEN
			PERFORM create_distributed_table('product_route', 'product_id', colocate_with => 'none');
		END IF;

	END IF;
END
$$;
SQL
}

############### create database schema
PGHOST="$COORDINATOR"
create_schema &>"$JOB_RESULT_DIR/schema-create.log"

################## Functions: generate data

### scale data size using scaling factor SCALE
scale_count() { awk -v b="$1" -v s="$SCALE" 'BEGIN{x=int(b*s+0.5);if(x<1)x=1;print x}'; }

### generate synthetic data
generate_data() {
	HOT_MERCHANTS=$((NUM_MERCHANTS * HOT_MERCHANT_PERCENT / 100))
	((HOT_MERCHANTS >= 1)) || HOT_MERCHANTS=1
	COLD_MERCHANTS=$((NUM_MERCHANTS - HOT_MERCHANTS))
	((COLD_MERCHANTS >= 1)) || COLD_MERCHANTS=1

	if [[ "$TRUNCATE_FIRST" == "1" ]]; then
		psqlx -c "TRUNCATE TABLE order_route;"
		psqlx -c "TRUNCATE TABLE product_route;"
		psqlx -c "TRUNCATE TABLE order_items,orders,inventory,products,customers,merchants CASCADE;"
	fi

	psqlx <<SQL
INSERT INTO merchants SELECT i,'Merchant-'||i,(ARRAY['North','South','East','West','Central'])[1+(i%5)] FROM generate_series(1::bigint, $NUM_MERCHANTS::bigint) g(i);

INSERT INTO customers SELECT i,1+((i::bigint - 1)%$NUM_MERCHANTS),'Customer-'||i,'customer-'||i||'@example.test',timestamp '2020-01-01'+(((i::bigint * 17))%2000)*interval '1 day' FROM generate_series(1::bigint, $NUM_CUSTOMERS::bigint) g(i);

INSERT INTO products SELECT i,1+((i::bigint - 1)%$NUM_MERCHANTS),'Product-'||i,'Category-'||(i%10),(1+(((i::bigint * 7919))%100000)/100.0)::numeric(12,2) FROM generate_series(1::bigint, $NUM_PRODUCTS::bigint) g(i);

INSERT INTO inventory SELECT product_id,merchant_id,product_id,10+((hashint8extended(product_id,$DATA_SEED)&9223372036854775807)%991)::int,current_timestamp FROM products;
SQL
	psqlx -c "\copy (SELECT product_id, inventory_id, merchant_id FROM inventory) TO '${DATA_ROOT}/product-route.csv' WITH (FORMAT csv)"
	psqlx -c "\copy product_route (product_id, inventory_id, merchant_id) FROM '${DATA_ROOT}/product-route.csv' WITH (FORMAT csv)"
	rm -f "${DATA_ROOT}/product-route.csv"

	psqlx <<SQL
WITH g AS (
  SELECT i::bigint,(hashint8extended(i,$DATA_SEED)&9223372036854775807) h1,(hashint8extended(i,$((DATA_SEED + 1)))&9223372036854775807) h2 FROM generate_series(1::bigint, $NUM_ORDERS::bigint) g(i)
), m AS (
  SELECT i::bigint,CASE WHEN (h1%10000)<($HOT_ORDER_PERCENT*100) THEN 1+(h2%$HOT_MERCHANTS) ELSE $HOT_MERCHANTS+1+(h2%$COLD_MERCHANTS) END::bigint merchant_id FROM g
)
INSERT INTO orders
SELECT i::bigint,merchant_id,merchant_id+$NUM_MERCHANTS*((hashint8extended(i,$((DATA_SEED + 2)))&9223372036854775807)%((($NUM_CUSTOMERS-merchant_id)/$NUM_MERCHANTS)+1)),
       'COMPLETED',0.00,current_timestamp-(((i::bigint * 31))%365)*interval '1 day' FROM m;
SQL

	psqlx <<SQL
WITH g AS (
 SELECT i order_item_id,1+((i::bigint - 1)%$NUM_ORDERS) order_id,(hashint8extended(i,$((DATA_SEED + 10)))&9223372036854775807) ph,
        1+((hashint8extended(i,$((DATA_SEED + 11)))&9223372036854775807)%5)::int qty FROM generate_series(1::bigint, $NUM_ORDER_ITEMS::bigint) g(i)
), x AS (SELECT g.*,o.merchant_id FROM g JOIN orders o USING(order_id)),
y AS (SELECT *,merchant_id+$NUM_MERCHANTS*(ph%((($NUM_PRODUCTS-merchant_id)/$NUM_MERCHANTS)+1)) product_id FROM x)
INSERT INTO order_items
SELECT y.order_item_id,y.merchant_id,y.order_id,y.product_id,y.qty,p.price
FROM y
JOIN products p
  ON p.merchant_id=y.merchant_id
 AND p.product_id=y.product_id;

UPDATE orders o
SET total_amount=x.total
FROM (
  SELECT merchant_id,order_id,SUM(quantity*unit_price)::numeric(12,2) total
  FROM order_items
  GROUP BY merchant_id,order_id
) x
WHERE o.merchant_id=x.merchant_id
  AND o.order_id=x.order_id;
SQL
	psqlx -c "\copy (SELECT order_id, merchant_id FROM orders) TO '${DATA_ROOT}/order-route.csv' WITH (FORMAT csv)"
	psqlx -c "\copy order_route (order_id, merchant_id) FROM '${DATA_ROOT}/order-route.csv' WITH (FORMAT csv)"
	rm -f "${DATA_ROOT}/order-route.csv"
	[[ "$RUN_ANALYZE" == "1" ]] && psqlx -c "ANALYZE;"
	echo "Synthetic data generation complete. Default scale creates about $((NUM_ORDER_ITEMS / NUM_ORDERS)) historical items/order."
}

################## generate data
PGHOST="$COORDINATOR"
NUM_MERCHANTS="${NUM_MERCHANTS:-$(scale_count 1000)}"
NUM_CUSTOMERS="${NUM_CUSTOMERS:-$(scale_count 1000000)}"
NUM_PRODUCTS="${NUM_PRODUCTS:-$(scale_count 500000)}"
NUM_ORDERS="${NUM_ORDERS:-$(scale_count 5000000)}"
NUM_ORDER_ITEMS="${NUM_ORDER_ITEMS:-$(scale_count 15000000)}"
TRUNCATE_FIRST="${TRUNCATE_FIRST:-1}"
RUN_ANALYZE="${RUN_ANALYZE:-1}"
generate_data &>"$JOB_RESULT_DIR/data-generation.log"
echo "Checking PostgreSQL servers after data loading..."
check_server_steps || fail "Cluster health check failed after data generation"

############### Explain transaction statements
# EXPLAIN without ANALYZE plans statements without running their data changes.
# The helper reads the copied pgbench scripts and supplies representative values
# for their pgbench variables; it never invokes pgbench.
command -v python3 >/dev/null 2>&1 || fail "python3 not found"
mkdir -p "$RUN_DIR"
python3 "$SCRIPT_DIR/explain_transactions.py" \
    --transactions "$TX_DIR" \
    --output "$RUN_DIR" \
    --psql "$PSQL" \
    --host "$PGHOST" \
    --port "$PGPORT" \
    --user "$PGUSER" \
    --database "$PGDATABASE" \
    --num-merchants "$NUM_MERCHANTS" \
    --num-customers "$NUM_CUSTOMERS" \
    --num-products "$NUM_PRODUCTS" \
    --num-orders "$NUM_ORDERS" \
    --hot-merchants "$HOT_MERCHANTS" \
    --report-days "$REPORT_DAYS" \
    >"$EXPLAIN_LOG_FILE" 2>&1
info "EXPLAIN results: $RUN_DIR"
info "Experiment complete: $JOB_RESULT_DIR"
