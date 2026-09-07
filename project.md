# CS4224/CS5424 Project (25 marks)

[2610] 2026/2027 Semester 1

## Table of Contents

1. Project Policies
2. Baseline Database Schema
3. Baseline Citus Design
4. Transaction Workloads
5. Project Tasks
6. Getting Started
    6.1. SoC Compute Cluster
    6.2. Accessing Servers Remotely
    6.3. Cluster Home Directory and /tmp
    6.4. Project Team Accounts
    6.5. Getting Help
7. Project Files
    7.1. install_citus_slurm.sh
    7.2. Experiment Files: expt_a0 and expt_b0
    7.3. run.sh
8. Synthetic Dataset
9. Benchmark Metrics
    9.1. summary.csv
    9.2. transaction_metrics.csv
10. Slurm Results Directory
    10.1. benchmark-results/
    10.2. logs/
    10.3. metrics-cN/
11. Project Deliverables
    11.1. Result Folder
    11.2. Report File
    11.3. Additional Report Files
    11.4. How to Submit
12. Project Evaluation
13. Resources

The objective of this project is to provide students with the opportunity to acquire practical experience using a distributed database system to optimize the performance of an application. The learning tasks in this project involve the following: how to install a distributed database system on a cluster of machines, how to design a data model and implement transactions to support an application by taking into consideration the workload of the application and the features/limitations of the database system, and how to optimize and benchmark the performance of an application.

In this project, you are the database performance engineer for a multi-tenant order-processing application. Your objective is to tune the performance of the application running on Citus 14.1.0 (with PostgreSQL 18.6). You will be using the servers in the SoC compute cluster (which is managed by Slurm), PostgreSQL’s frontend client psql to interact with the database system, and pgbench for running benchmark tests.

The project deliverables are due on October 30 (Friday, 2359).

## 1. Project Policies

Late submission policy: Any submission that is late by one day will incur a penalty of 2 marks; any submission that is late by two days will incur a penalty of 4 marks; and any submission that is late by more than two days will not be graded and will receive 0 marks. Late days are rounded up to the nearest integer. For example, a submission that is late by 1 hour will count as 1 day late. So, if your code submission is late by 5 hours and your final report is late by 30 hours, your total penalty will be 6 marks.

You should review the course’s policy on plagiarism (lecture 0, slide 19 onwards).

You are allowed to use AI tools for the project; if the project was completed with the help of an AI tool, you must follow the guidelines to acknowledge its use and preserve all interactions with the AI tool. Specifically, if an AI tool was used in the project, submit a PDF report with information on how each AI tool was used: either list the prompts and their outputs, or submit a PDF showing the interactions with the AI tool.

## 2. Baseline Database Schema

The multi-tenant application hosts multiple merchants, where each merchant maintains data on his/her products, product inventory, customers, customer orders, and their order items.

The baseline database schema is organized into the following 6 tables.

```sql
CREATE TABLE merchants (
    merchant_id BIGINT PRIMARY KEY,
    merchant_name TEXT NOT NULL,
    region TEXT NOT NULL
);

CREATE TABLE customers (
    customer_id BIGINT PRIMARY KEY,
    merchant_id BIGINT NOT NULL,
    customer_name TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE products (
    product_id BIGINT PRIMARY KEY,
    merchant_id BIGINT NOT NULL,
    product_name TEXT NOT NULL,
    category TEXT,
    price NUMERIC(12,2) NOT NULL
);

CREATE TABLE inventory (
    inventory_id BIGINT PRIMARY KEY,
    merchant_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INTEGER NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CHECK (quantity >= 0)
);

CREATE TABLE orders (
    order_id BIGINT PRIMARY KEY,
    merchant_id BIGINT NOT NULL,
    customer_id BIGINT NOT NULL,
    order_status TEXT NOT NULL,
    total_amount NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    CHECK (total_amount >= 0)
);

CREATE TABLE order_items (
    order_item_id BIGINT PRIMARY KEY,
    merchant_id BIGINT NOT NULL,
    order_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(12,2) NOT NULL,
    CHECK (quantity > 0),
    CHECK (unit_price >= 0)
);
```

The usual foreign-key constraints apply to the above schema: merchant_id is a foreign key that references merchants, product_id is a foreign key that references products, customer_id is a foreign key that references customers, and order_id is a foreign key that references orders. These foreign-key constraints are omitted from the baseline schema.

## 3. Baseline Citus Design

The tables in the baseline database schema are distributed as follows:

```sql
SELECT create_distributed_table('customers', 'customer_id');
SELECT create_distributed_table('products', 'product_id');
SELECT create_distributed_table('inventory', 'inventory_id');
SELECT create_distributed_table('orders', 'order_id');
SELECT create_distributed_table('order_items', 'order_item_id');
```

Five explicit indexes are created for the baseline design: customers.merchant_id, products.merchant_id, inventory.merchant_id, orders.merchant_id, and order_items.merchant_id.

## 4. Transaction Workloads

The application’s transaction workload consists of 9 transactions (T1 to T9) with two workload configurations (workloads A and B). The last two columns (labelled Weight A and Weight B) indicate the percentage of each transaction in workloads A and B, respectively. Among the 9 transactions, most concern a single merchant, but some span merchants or the entire database.

| Transaction | Description | Weight A (%) | Weight B (%) |
|---|---|---:|---:|
| T1 | Place Order | 36 | 10 |
| T2 | Update Inventory | 20 | 10 |
| T3 | Customer Order History | 10 | 5 |
| T4 | Product Lookup | 10 | 5 |
| T5 | Update Order Status | 10 | 10 |
| T6 | Global Sales | 5 | 10 |
| T7 | Inventory Transfer | 5 | 30 |
| T8 | Update Customer | 2 | 10 |
| T9 | Update Product | 2 | 10 |

The following provides an overview of the transactions; a baseline implementation of these transactions will be provided.

T1 creates a new customer order for a merchant. Given a merchant and customer pair, T1 first retrieves the customer name and email, and creates a new order for the customer (with order status = "pending") consisting of one to five order items.

T2 updates the quantity for a specified inventory record given the merchant_id, inventory_id, product_id, and the quantity adjustment. The transaction preserves the constraint that quantity must be non-negative.

T3 displays information (from orders and order_items) about the 20 most recent orders (in descending order of created_at) for a given merchant and customer pair.

T4 retrieves the product information (from products and inventory) for a given merchant and product pair.

T5 updates the order_status for a given order.

T6 shows the top-20 merchants in terms of their total revenue for orders created within a specified period of time. The records are sorted in descending order of total revenue, and the information shown includes merchant_id, total number of orders created for that period, and total revenue for that period.

T7 updates the quantity for two specified products. Given a source product_id, a destination product_id, and a transfer quantity T, T7 deducts the source product’s quantity by T and increments the destination product’s quantity by T. The transaction preserves the constraint that quantity must be non-negative.

T8 updates the email address of a specified customer given a merchant and customer pair.

T9 increases the price of a specified product.

## 5. Project Tasks

There are five tasks in this project.

Task 1: Benchmark the performance of the baseline database design for workload A by varying the number of clients. The scripts for this benchmarking experiment (named expt_a0) will be provided.

You may also run additional experiments to study the effects of other parameters (e.g., the number of worker nodes, skewness, or scaling factor of the synthetic data) on the transaction throughput/latency performance metrics of the baseline design for workload A.

Task 2: Optimize the performance of the application for workload A. The main performance metric to optimize is the average transaction throughput. Your optimizations could involve modifying the database design (e.g., database schema, data distribution, index), tuning PostgreSQL/Citus parameters, re-implementing the transactions (e.g., using stored procedures), etc.

This task involves running multiple benchmark experiments to quantify the effectiveness of the various optimizations that you introduce. One possible approach is to optimize the application progressively as follows. Starting with the baseline design (denoted as version V0), you add an optimization (denoted as O1) to V0 to obtain an improved design V1, further refine V1 with another optimization O2 to obtain V2, and so on until you arrive at your final design Vn (which incorporates optimizations O1 to On). Each of the improved designs should be benchmarked with an experiment; i.e., create experiment expt_ai to benchmark version Vi for workload A. Another possible approach to quantify the effectiveness of the optimizations (O1 to On) in your final version Vn is to create an experiment expt_ai for each Oi to benchmark the version that includes all the optimizations except Oi.

Your project report should discuss and interpret the findings of each experiment (or the subset of your most important/interesting/surprising experimental results). As an example of an interesting experiment, you might have thought of two possible optimizations to improve a design, and your experimental results show that applying each optimization separately improves performance more significantly than applying both optimizations together. As an example of a surprising experimental result, you might have thought that applying an optimization should improve the performance of a design, but the experimental results proved otherwise.

Task 3: Similar to Task 1, this task is to benchmark the performance of the baseline database design for workload B by varying the number of clients. The scripts for this benchmarking experiment (named expt_b0) will be provided. Here again, you may conduct additional experiments to investigate the performance of the baseline design for workload B.

Task 4: Similar to Task 2, this task is to optimize the performance of the application for workload B.

Task 5: Submit the project deliverables (including a project report); the details of what to submit are described in Project Deliverables.

## 6. Getting Started

### 6.1. SoC Compute Cluster

The project will be done using the SoC Computer Cluster running Ubuntu Linux. To use the SoC compute cluster, you must have an SoC Account and enable "SoC Compute Cluster" in MySoC. Non-SoC students may proceed to the following URL to create/re-enable their SoC account: https://mysoc.nus.edu.sg/~newacct

If you’ve forgotten your SoC account password, proceed to the MySoC portal to reset your SoC account password. Log in using your NUS-ID (without domain) and password, and click MySoC Account > Reset password. If you have forgotten your NUS-ID and password, please refer to https://nusit.nus.edu.sg/change-or-reset-your-nus-id-password.

To log in to a cluster server from your PC, you need to have a SSH client installed on your PC. Linux and macOS users should already have an SSH client installed by default. Windows users could install Windows Subsystem for Linux (WSL) and use Linux. You could also use other SSH clients such as PuTTY.

The servers can only be accessed from within SoC networks. If you want to access them from outside SoC, refer to Accessing Servers Remotely.

The servers are managed using the Slurm Workload Manager; refer to https://dochub.comp.nus.edu.sg/cf/guides/compute-cluster/access for information on how to access the cluster.

The cluster servers are classified into login nodes (xlogin[12]) and compute nodes (xcn*, xgp*). Login nodes are for interactive access, job submission, job monitoring, and other interaction with Slurm. It suffices to use the hostname xlogin.comp.nus.edu.sg, which randomly selects one of the actual login nodes in the Compute Cluster. Please do not use login nodes to run heavy compute jobs. The compute nodes are where jobs submitted to Slurm are executed.

Although Slurm is designed primarily for submitting batch jobs, it also supports interactive shell access to a server. The following example (adapted from the Slurm Quick Start Guide) illustrates how to use Slurm’s salloc and srun commands.

```console
$ ssh alice@xlogin.comp.nus.edu.sg
alice@xlogin1:~$ salloc
salloc: Granted job allocation 7763
alice@xlogin1:~$ srun --pty bash
alice@xcnb0:~$ hostname
xcnb0
alice@xcnb0:~$ exit
exit
alice@xlogin1:~$ exit
exit
salloc: Relinquishing job allocation 7763
alice@xlogin1:~$
```

To learn more about how to use Slurm, refer to https://dochub.comp.nus.edu.sg/cf/guides/compute-cluster/slurm-info and https://dochub.comp.nus.edu.sg/cf/guides/compute-cluster/slurm-quick. For information on the hardware configuration of the compute nodes, refer to https://dochub.comp.nus.edu.sg/cf/guides/compute-cluster/hardware.

### 6.2. Accessing Servers Remotely

Note that the servers can only be accessed from within SoC networks. If you want to access them from outside SoC, there are two options.

The first option is to access them via NUS VPN using the Cisco Secure Client. For instructions on how to install the Cisco Secure Client application, refer to https://nusit.nus.edu.sg/eguides.

The second option is to access them via SoC’s SSH jump host service. This is a simple SSH jump service that provides all SoC users with SSH access to selected servers and subnetworks inside SoC. Users must authenticate with both a password and an SSH public key. By default, remote access is permitted when you are connecting from within NUS, and users connecting from outside NUS must connect to the NUS VPN first before using this service. Using the jump host service requires a one-time setup of your SSH public keys on your PC and the jump host. Refer to https://dochub.comp.nus.edu.sg/cf/guides/skeys and https://dochub.comp.nus.edu.sg/cf/guides/sjump/putty for instructions on how to set up your SSH public keys.

### 6.3. Cluster Home Directory and /tmp

The Cluster Home Directory is the home directory in the SoC Compute Cluster, and it is accessible on every cluster node. Although your cluster home directory is on redundant, distributed storage, it is not backed up. You are advised to perform your own backups where necessary.

Note that the Cluster Home Directory, being on NFS, may not be best suited for active compute jobs, especially if they depend on heavy storage I/O. You should consider using local flash storage (/tmp) on individual nodes if your jobs require heavy storage I/O.

The files/directories you create on Linux, by default, have permissions that allow other users to read them. To ensure that the files/directories you create are accessible only by your account and no other account, you can use the chmod command to change the permissions of the created files/directories. A more convenient way is to configure this using the umask command by adding the following line to your ~/.bash_profile file:

umask u=rwx,g=,o=

### 6.4. Project Team Accounts

While you may access the compute cluster servers using your own SoC account, it is more convenient for each project team to have shared access using a project team account.

Information about your project team account will be emailed to you by September 4.

### 6.5. Getting Help

For technical support on using the servers, please create a ticket using an appropriate category (e.g., "Computer Clusters & Unix Servers", "Network & Connectivity") at https://rt.comp.nus.edu.sg/.

You may also approach Technical Services (01-06, level 1, COM1) for technical help with using the servers.

If you are new to the Linux environment, refer to the learning resources in Resources.

## 7. Project Files

To obtain the project files, ssh to a login server using your SoC user ID (e.g., ssh alice@xlogin.comp.nus.edu.sg) or your project team account. In the rest of this document, assume that "$" is the prompt of your login shell.

Run the following commands to download the project files.

```console
$ cd $HOME
$ wget https://www.comp.nus.edu.sg/~cs4224/citus_project.zip
$ unzip citus_project.zip
$ cd citus_project
```

citus_project/ consists of the following files:

```text
citus_project/
|-- expt_a0/
|-- expt_b0/
|-- install_citus_slurm.sh
|-- README.md
```

### 7.1. install_citus_slurm.sh

The bash script install_citus_slurm.sh is used to install Citus on your cluster home directory. This installation is a one-time operation that will install the following files:

```text
$HOME/pgsql
|-- bin/
|-- include/
|-- lib/
|-- share/
```

The installed files at $HOME/pgsql will be used for the benchmarking experiments.

The lines that begin with "#SBATCH" in install_citus_slurm.sh are directives for Slurm. For example, the directive "#SBATCH --partition=normal" is used to specify the type of partition (i.e., queue) to which your Slurm job is submitted. Here, the normal partition is used for short-duration jobs (with a maximum of 3 hours) that do not require a GPU. Refer to Slurm Cluster Information for more information about the Slurm configuration in the SoC compute cluster.

Before executing install_citus_slurm.sh, you should modify the directive "#SBATCH --mail-user=alice_and_bob@u.nus.edu" with your own email address to receive an email notification when your Slurm job starts and terminates.

To install Citus, execute the script using Slurm’s sbatch command:

```console
$ cd citus_project
$ chmod u+x *.sh
$ sbatch install_citus_slurm.sh
```

### 7.2. Experiment Files: expt_a0 and expt_b0

The two directories expt_a0/ and expt_b0/ contain the files for Task 1 and Task 3, respectively.

Use the following naming convention for all your experiment directories: expt_wN denotes experiment N for workload w, where w ∈ {a,b}, and N is a non-negative integer. For example, if you run two additional experiments for workload A, the directories for these additional experiments could be named expt_a1 and expt_a2.

Each experiment directory consists of a bash script named run.sh to run the benchmarking experiment and a directory transactions/ that contains the implementation of the 9 transactions:

```text
expt_a0/
|-- run.sh
|-- transactions/
    |-- T1_place_order.sql
    |-- T2_update_inventory.sql
    |-- T3_order_history.sql
    |-- T4_product_lookup.sql
    |-- T5_update_order_status.sql
    |-- T6_global_sales.sql
    |-- T7_inventory_transfer.sql
    |-- T8_update_customer.sql
    |-- T9_update_product.sql
```

The transactions are implemented using a combination of SQL and psql’s meta-commands (commands that begin with the backslash character; e.g., \set).

The files in expt_a0/ and expt_b0/ are equivalent except for the file run.sh which differ in the value assigned to the WORKLOAD variable.

### 7.3. run.sh

The bash script run.sh (to be submitted via Slurm’s sbatch command) is used to execute the benchmarking for a given workload.

Here again, you should modify the directive "#SBATCH --mail-user=alice_and_bob@u.nus.edu" in run.sh with your own email address to receive an email notification when your Slurm job starts and terminates.

To ensure that different project teams do not use use the same PGPORT number for their PostgreSQL servers, it is important that you modify line 21 in run.sh to replace 99 with your project team number for the TEAM_ID variable. As an example, line 21 should be modified to the following for project team 5:

TEAM_ID=${TEAM_ID:5}

When run.sh is submitted to Slurm for execution, the script will be executed only on the first allocated node; for convenience, we use the first allocated node as the coordinator node and the remaining allocated nodes as worker nodes. To execute a bash command on a specific worker node, run.sh uses Slurm’s srun command.

run.sh performs the following key steps:  each node  initializes the database cluster and starts the database server; the coordinator node creates the database schema,  generates synthetic data for the database, and executes pgbench to run the benchmarking.

During the execution of run.sh, various log files are created, and run.sh ends by creating several text files containing various derived performance throughput/latency metrics. A directory named slurm-results is created (within the experiment directory) to contain all the output files generated by run.sh. More details about slurm-results/ are described in Slurm Results Directory.

Here’s how you could execute the first experiment for Task 1:

```console
$ cd expt_a0
$ chmod +x *.sh
$ sbatch run.sh
```

You can use Slurm’s squeue command to check the job status of the submitted Slurm job:

```console
$ squeue -u "$USER"
```

You may also examine the contents of the output files in slurm-results/ to view the progress of the benchmarking.

## 8. Synthetic Dataset

In the provided run.sh, there is a variable named SCALE that controls the scaling factor of the generated synthetic data.

Using the default SCALE=1, the cardinality of the default dataset is as follows:

| Table | Rows |
|---|---:|
| merchants | 1,000 |
| customers | 1,000,000 |
| products | 500,000 |
| inventory | 500,000 |
| orders | 5,000,000 |
| order_items | 15,000,000 |

The default data has the following workload skew: 10% of merchants receive approximately 50% of order activity.

## 9. Benchmark Metrics

The provided run.sh collects both workload-level and per-transaction latency measurements. The measured run uses pgbench’s per-transaction logging (-l) so that the latency distribution can be calculated from individual completed transactions rather than only from pgbench’s aggregate summary. By default, run.sh uses LOG_SAMPLE_RATE=1.0 so that every successfully logged transaction is included in the latency calculations.

### 9.1. summary.csv

In the provided run.sh, the benchmarking is performed by varying the number of clients. For each client count, the benchmark writes one row to the output file summary.csv. The columns in summary.csv are:

| Column | Meaning |
|---|---|
| clients | Number of concurrent pgbench clients used for that measured run. |
| successful_transactions | Number of successfully logged transactions in the measured interval. |
| failed_log_records | Number of pgbench log records that did not contain a numeric latency value. Treat this as a diagnostic indicator and inspect the raw pgbench output and PostgreSQL logs when it is non-zero. |
| overall_tps | Successful logged transactions divided by the configured measured duration. |
| overall_avg_latency_ms | Arithmetic mean of the latency of all successfully logged transactions, in milliseconds. |
| overall_median_latency_ms | Median latency of all successfully logged transactions. This is the same as the overall p50 latency. |
| overall_p95_latency_ms | 95th-percentile latency for the complete transaction mix. Approximately 95% of successfully logged transactions completed at or below this latency. |
| overall_p99_latency_ms | 99th-percentile latency for the complete transaction mix. This tail-latency metric is useful for detecting configurations that improve average performance while producing a small number of very slow transactions. |
| retried_transactions | Number of pgbench transactions that had to be retried at least once. |
| total_retries | Total retry attempts across all transactions. One transaction can contribute more than one retry. |
| serialization_failures | Number of serialization failures reported in pgbench’s detailed failure summary. |
| deadlock_failures | Number of deadlock failures reported in pgbench’s detailed failure summary. |
| pgbench_exit_code | Exit status of the pgbench process for that measured run. 0 means pgbench completed normally; non-zero means pgbench reported some run-level failure condition. |

The benchmark provides both central-tendency and tail-latency measures. Do not judge a design only by average latency: compare p50, p95, and p99 as the number of clients increases.

### 9.2. transaction_metrics.csv

The output file transaction_metrics.csv contains one row for every enabled transaction type at every tested client count. Its columns are:

| Column | Meaning |
|---|---|
| clients | Number of concurrent pgbench clients. |
| transaction | Transaction identifier: T1, T2, …​, T9. |
| name | Human-readable transaction name, such as Place Order or Global Sales. |
| successful_transactions | Number of successfully logged executions of that transaction type. |
| tps | Successful executions of that transaction type divided by the measured duration. |
| avg_latency_ms | Mean latency for that transaction type. |
| p50_latency_ms | Median latency for that transaction type. |
| p95_latency_ms | 95th-percentile latency for that transaction type. |
| p99_latency_ms | 99th-percentile latency for that transaction type. |

For each measured client count, pgbench writes a transaction log containing one latency observation per logged transaction. The script run.sh extracts the latency values, sorts them numerically, and selects the observations corresponding to p50, p95, and p99. Latencies in the pgbench log are in microseconds; run.sh converts them to milliseconds in the CSV summary files. The same calculation is performed once for the complete transaction mix and once for each transaction type.

## 10. Slurm Results Directory

Each execution of run.sh creates a job-specific directory under slurm-results.

Here’s an example of the files created under slurm-results:

```text
slurm-results/
`-- job-123456/
    |-- benchmark.log
    |-- data-generation.log
    |-- schema-create.log
    |-- server_versions.log
    |-- topology.txt
    |-- xcnc0-postgresql.log
    |-- ...
    `-- benchmark-results/
            |-- config.txt
            |-- latency-summary-c1.txt
            |-- latency-summary-c4.txt
            |-- logs/
            |   |-- pgbench-c1.*
            |   |-- pgbench-c4.*
            |   |-- transactions-c1.log
            |   `-- transactions-c4.log
            |-- metrics-c1/
            |-- metrics-c4/
            |-- README-metrics.txt
            |-- result-c1.txt
            |-- result-c4.txt
            |-- summary.csv
            |-- transaction_metrics.csv
            |-- warmup-c1.txt
            |-- warmup-c4.txt
```

benchmark.log

    Log file generated during the benchmarking. Inspect this first if pgbench reports a failure.
data-generation.log

    Log file generated during synthetic data generation.
schema-create.log

    Log file generated while creating the baseline schema and tables.
server_versions.log

    Records the PostgreSQL and Citus versions used by the coordinator.
topology.txt

    Records the coordinator and worker nodes selected for the job.

`<hostname>-postgresql.log`

    PostgreSQL server log from each coordinator/worker node. These files are especially important if pgbench reports that a backend died, a connection was lost, or a distributed query failed. Compare timestamps in benchmark.log with the PostgreSQL logs to identify the failing node and SQL statement.

### 10.1. benchmark-results/

config.txt

    Records the benchmark settings used for the run.
latency-summary-cN.txt

    A compact text summary of the overall latency metrics for client count N. This is convenient for quick inspection; summary.csv should normally be used for systematic analysis.
result-cN.txt

    Raw output from the measured pgbench run with N clients. It contains pgbench progress and aggregate statistics.
summary.csv

    The main workload-level results file. It contains overall TPS, overall average latency, median/p50 latency, p95 latency, and p99 latency for each client count.
transaction_metrics.csv

    The main per-transaction results file. It contains transaction count, transaction TPS, and average/p50/p95/p99 latency for every transaction type and client count.
warmup-cN.txt

    Output from the warmup run.
README-metrics.txt

    Short machine-generated description of the benchmark metrics and output files.

### 10.2. logs/

The logs/ directory contains the raw per-transaction logs generated by pgbench. Files beginning with pgbench-cN are the original log files produced by the pgbench worker threads for client count N. The benchmark concatenates these into transactions-cN.log for analysis. These files are the source data for the latency percentiles in summary.csv and transaction_metrics.csv.

### 10.3. metrics-cN/

For each client count N, the benchmark creates a metrics-cN/ directory. It contains intermediate files used to calculate the CSV summaries, including:

```text
all-latency-us.txt
T1-latency-us.txt
T2-latency-us.txt
T3-latency-us.txt
T4-latency-us.txt
T5-latency-us.txt
T6-latency-us.txt
T7-latency-us.txt
T8-latency-us.txt
T9-latency-us.txt
failed-log-records.txt
```

The latency sample files use microseconds, matching the pgbench transaction-log unit. The final CSV files report milliseconds.

failed-log-records.txt contains log records for which the benchmark could not extract a numeric latency. A non-empty file should trigger investigation of result-cN.txt, benchmark.log, and the per-node PostgreSQL logs.

## 11. Project Deliverables

The project deliverables consist of three components: (1) a result folder containing all your experimental scripts, transaction code, and output files; (2) a project report file (in PDF format); and (3) additional files (in PDF format), if an AI tool was used in the project.

In the following, NN denotes your project team number (e.g., 01, 02, …​, 20).

### 11.1. Result Folder

The result folder must be named citus_project_team_NN.

Here’s an example showing the contents of this folder for team 99:

```text
citus_project_team_99/
|-- expt_a0/
    |-- citus-123456.err
    |-- citus-123456.out
    |-- run.sh
    |-- slurm-results/
        |-- job-123456/
    |-- transactions/
|-- expt_a1/
|-- ...
|-- expt_b0/
|-- expt_b1/
|-- ...
|-- install_citus_slurm.sh
|-- README.md
```

This folder must contain a sub-folder for each of your experiments. The sub-folder must be named following the naming convention expt_wN, where N is a non-negative integer denoting the experiment number and w ∈ {a,b} denotes the workload.

The README.md file provides a description for each of the experiment sub-folders.

Each experiment sub-folder contains the following files: (a) the bash script run.sh for the experiment, (b) transactions/ containing the transaction implementations, (c) slurm-results/ containing a folder named job-<slurm-job-id> with the output files created by the experiment, and (d) the two log files citus-<job-id>.* created by Slurm.

Create a zip folder named NN_files.zip from your result folder named citus_project_team_NN/:

```console
$ zip -r NN_files.zip citus_project_team_NN
```

### 11.2. Report File

Your project report file should be named NN_report.pdf. The report length should be at most 20 pages (with a font size of at least 10).

Your report should use the following structure (containing at least a cover page and 6 sections):

- The cover page states the following: (a) project team number, (b) list of team member names, and (c) list of AI tools used in the project (indicate "NONE" if no AI tool was used).

- Section 1 lists the team member contributions to the project: for each team member, state the tasks contributed by that student.

- Section 2 is for Task 1 (baseline design for workload A).

- Section 3 is for Task 2 (optimized design for workload A).

- Section 4 is for Task 3 (baseline design for workload B).

- Section 5 is for Task 4 (optimized design for workload B).

- Section 6 is the report’s conclusion, which could discuss any lessons learnt, difficulties encountered, etc.

- A list of all references (e.g., books, papers, websites) consulted for the project.

For each of sections 2 to 5, the report should be organized into sub-sections, with each sub-section presenting the findings and analysis of an experiment. The experiment number (e.g., expt_a4) should be stated for each experiment to correspond to the submitted result files. The experimental results should be presented using appropriate graphs/tables (e.g., using a graph to compare the transaction throughput/latencies as a function of some parameter value). Any claim made in the report (e.g., optimization X is more effective than optimization Y) should be supported by experimental evidence. As it might not be possible to discuss all your experimental results within the report’s page limit, you should present the most important/interesting/surprising experimental results in your report.

### 11.3. Additional Report Files

If you have indicated that some AI tool was used on the cover page, you must submit at least one additional report file describing how each AI tool was used for the project tasks.

Each additional report file should be named NN_X.pdf, where X is some appropriate descriptive text (e.g., 99_chatgpt_log.pdf, 99_ai_tool_usage.pdf).

Your team does not need to submit any additional report file if no AI tool was used.

### 11.4. How to Submit

Each team should submit at least two files in total; do not make multiple submissions of each file.

(1) Upload the zip file NN_files.zip for your result folder into Canvas > Assignments > Project Result Files folder.

(2) Upload your project report named NN_report.pdf into Canvas > Assignments > Project Report folder.

(3) If you have used an AI tool for the project, create a zip file named NN_ai_tool.zip containing all the additional report files and upload the zip file into Canvas > Assignments > Project AI Tool Usage Files folder. Here’s an example of how to create the zip file from your additional report files:

```console
$ zip NN_ai_tool.zip  NN_chatgpt.pdf NN_claude.pdf NN_ai_tool_usage.pdf
```

Your team does not need to upload any file for (3) if no AI tool was used.

## 12. Project Evaluation

Your project will be evaluated based on the quality of your design decisions, experimental designs,  analysis/interpretation of experimental results, and the project report.

There will be a 20-minute project evaluation session for each team during week 13. Each evaluation session is a Q&A session; there will be no student presentation. All team members are expected to attend the evaluation session. Registration for the evaluation sessions will be announced in week 12.

## 13. Resources

- Citus https://www.citusdata.com/

  - Citus 14 https://learn.microsoft.com/en-us/postgresql/citus/?view=citus-14

- PostgreSQL 18 https://www.postgresql.org/docs/18/index.html

  - pgbench https://www.postgresql.org/docs/current/pgbench.html

  - psql https://www.postgresql.org/docs/current/app-psql.html

- NUS VPN

  - Install Cisco Secure Client on Windows

  - Install Cisco Secure Client on Mac

  - Install Cisco Secure Client on Linux

  - NUS IT eGuides

- SoC’s Compute Cluster

  - Accessing the Compute Cluster

  - Slurm Cluster Information

  - Slurm Quick Start Guide

  - Compute Cluster Disk Storage

  - Compute Cluster Hardware Configuration

  - SoC Account Policies

- Learning Linux

  - S. Matthews, T. Newhall, Kevin Webb, Dive Into Systems: A Gentle Introduction to Computer Systems, Appendix 2: Using Unix

  - Getting Started with Linux

  - The Linux Command Line

  - UNIX Tutorial for Beginners

  - The Missing Semester of Your CS Education
