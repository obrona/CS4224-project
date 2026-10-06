#!/usr/bin/env bash

set -Eeuo pipefail

USERNAME="theodore"
JUMP_HOST="$USERNAME@stujump.comp.nus.edu.sg"
REMOTE_HOST="$USERNAME@xlogin.comp.nus.edu.sg"

# OpenSSH calls this script as its password-prompt helper. Other prompts (for
# example, first-time host-key confirmation or MFA) are relayed to the terminal.
if [[ ${TRANSFER_ASKPASS_MODE:-0} == 1 ]]; then
	prompt=${1:-"SSH prompt"}
	if [[ ${prompt,,} == *password* ]]; then
		printf '%s\n' "${TRANSFER_PASSWORD:?}"
	else
		printf '%s ' "$prompt" > /dev/tty
		IFS= read -r response < /dev/tty
		printf '%s\n' "$response"
	fi
	exit 0
fi

for command_name in ssh rsync; do
	if ! command -v "$command_name" >/dev/null 2>&1; then
		printf 'Error: required command "%s" is not installed.\n' "$command_name" >&2
		exit 1
	fi
done

printf 'Transfer direction:\n'
printf '  1) Push: local -> remote\n'
printf '  2) Pull: remote -> local\n'
read -r -p 'Choose 1 or 2: ' direction

case "$direction" in
	1 | push | PUSH)
		direction=push
		read -r -p 'Local source file or folder: ' source_folder
		read -r -p 'Remote destination folder: ' destination_folder
		;;
	2 | pull | PULL)
		direction=pull
		read -r -p 'Remote source file or folder: ' source_folder
		read -r -p 'Local destination folder: ' destination_folder
		;;
	*)
		printf 'Error: choose 1 (push) or 2 (pull).\n' >&2
		exit 1
		;;
esac

if [[ -z $source_folder || -z $destination_folder ]]; then
	printf 'Error: source and destination paths cannot be empty.\n' >&2
	exit 1
fi

# A trailing slash means "copy the contents" to rsync. Remove it so this
# script consistently copies the source folder itself. This has no effect on
# ordinary file paths.
if [[ $source_folder != / ]]; then
	source_folder=${source_folder%/}
fi

if [[ $direction == push && ! -f $source_folder && ! -d $source_folder ]]; then
	printf 'Error: local source is not a regular file or directory: %s\n' \
		"$source_folder" >&2
	exit 1
fi

if [[ $direction == pull ]]; then
	mkdir -p -- "$destination_folder"
fi

read -r -s -p "Password for $USERNAME: " TRANSFER_PASSWORD
printf '\n'
if [[ -z $TRANSFER_PASSWORD ]]; then
	printf 'Error: password cannot be empty.\n' >&2
	exit 1
fi

export TRANSFER_PASSWORD
export TRANSFER_ASKPASS_MODE=1
export SSH_ASKPASS_REQUIRE=force
export DISPLAY=${DISPLAY:-transfer-script}
SSH_ASKPASS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
export SSH_ASKPASS

cleanup() {
	unset TRANSFER_PASSWORD TRANSFER_ASKPASS_MODE SSH_ASKPASS_REQUIRE SSH_ASKPASS
}
trap cleanup EXIT

ssh_command="ssh -J $JUMP_HOST"

if [[ $direction == push ]]; then
	printf 'Pushing "%s" to %s:"%s" ...\n' \
		"$source_folder" "$REMOTE_HOST" "$destination_folder"
	rsync --archive --human-readable --info=progress2 --protect-args \
		--rsh="$ssh_command" -- \
		"$source_folder" "$REMOTE_HOST:$destination_folder/"
else
	printf 'Pulling %s:"%s" to "%s" ...\n' \
		"$REMOTE_HOST" "$source_folder" "$destination_folder"
	rsync --archive --human-readable --info=progress2 --protect-args \
		--rsh="$ssh_command" -- \
		"$REMOTE_HOST:$source_folder" "$destination_folder/"
fi

printf 'Transfer complete.\n'
