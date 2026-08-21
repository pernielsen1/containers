#!/usr/bin/env bash
set -euo pipefail

HOST="serverhp.home"
KEY="$HOME/.ssh/id_ed25519"

if [[ ! -f "$KEY" ]]; then
    echo "No SSH key found at $KEY, generating one..."
    ssh-keygen -t ed25519 -f "$KEY" -N ""
fi

# ssh-copy-id itself will prompt for the password via SSH.
ssh-copy-id -o StrictHostKeyChecking=accept-new -i "${KEY}.pub" "$HOST"

echo "Testing passwordless login..."
if ssh -o BatchMode=yes "$HOST" true; then
    echo "Success: passwordless SSH to $HOST is working."
else
    echo "Passwordless login test failed." >&2
    exit 1
fi
