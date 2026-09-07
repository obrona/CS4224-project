#!/usr/bin/env bash
#SBATCH --partition=normal
#SBATCH --time 30
#SBATCH --job-name=install-citus
#SBATCH --error=./log_slurm_%j.err
#SBATCH --output=./log_slurm_%j.out
#SBATCH --mail-type=BEGIN,END,FAIL

# IMPORTANT - replace this with your email
#SBATCH --mail-user=alice_and_bob@u.nus.edu  

# Script to install citus at $HOME/pgsql
#
# References
# https://wiki.postgresql.org/wiki/Compile_and_Install_from_source_code
# https://github.com/citusdata/citus/blob/main/CONTRIBUTING.md

PG_VERSION=18.6
PG_FILE=postgresql-${PG_VERSION}.tar.gz
PG_SRCDIR=$HOME/postgresql-${PG_VERSION}

CITUS_VERSION=14.1.0
CITUS_SRCDIR=$HOME/citus-${CITUS_VERSION}

# INSTALL_DIR - directory containing installed PG binaries, libraries, etc.
INSTALL_DIR=$HOME/pgsql

# initialize directories
function init_directories() {
	if [ -d "${INSTALL_DIR}" ]; then
		\rm -rf "${INSTALL_DIR}"
	fi
	mkdir -p "${INSTALL_DIR}"
	if [ -d "${CITUS_SRCDIR}" ]; then
		\rm -rf "${CITUS_SRCDIR}"
	fi
}

# Download PostgreSQL source code
function download_postgres() {
	cd $HOME
	if [ ! -e "${PG_FILE}" ]; then
		wget "https://ftp.postgresql.org/pub/source/v${PG_VERSION}/${PG_FILE}"
		if [ ! -e "${PG_FILE}" ]; then
			echo "ERROR: ${PG_FILE} missing!"
			exit 1
		fi
	fi
	if [ -d "${PG_SRCDIR}" ]; then
		\rm -rf "${PG_SRCDIR}"
	fi
	tar xvfz "${PG_FILE}"
}

# Install PostgreSQL source code
function install_postgres() {
	if [ ! -d "${PG_SRCDIR}" ]; then
		echo "ERROR: ${PG_SRCDIR} missing!"
		exit 1
	fi
	cd "${PG_SRCDIR}"
	export CFLAGS="-O2"
	./configure --prefix="${INSTALL_DIR}"
	make clean
	make world
	make install
	# make install-docs
}

# Download Citus extension
function download_citus() {
	cd $HOME
	if [ -d "${CITUS_SRCDIR}" ]; then
		\rm -rf "${CITUS_SRCDIR}"
	fi
	wget "https://github.com/citusdata/citus/archive/refs/tags/v${CITUS_VERSION}.tar.gz" -O citus-${CITUS_VERSION}.tar.gz
	tar -xzf citus-${CITUS_VERSION}.tar.gz
	cd ${CITUS_SRCDIR}
}

# Install Citus extension
function install_citus() {
	if [ ! -d "${CITUS_SRCDIR}" ]; then
		echo "ERROR: ${CITUS_SRCDIR} missing!"
		exit 1
	fi
	cd "${CITUS_SRCDIR}"
	export PATH=${INSTALL_DIR}/bin:$PATH
	./configure --prefix="${INSTALL_DIR}" --exec_prefix="${INSTALL_DIR}"
	make
	make install-all prefix="${INSTALL_DIR}" exec_prefix="${INSTALL_DIR}"
}

init_directories
download_postgres
install_postgres
download_citus
install_citus
