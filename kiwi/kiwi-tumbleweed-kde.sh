#!/bin/sh

set -eu
umask 077

description_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
target_dir=${1:-"$description_dir/outdir-Tumbleweed-KDE-$(date +%Y%m%d-%H%M%S)"}
signing_key=${2:-"$description_dir/../.keys/asahi.asc"}

if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != aarch64 ]; then
    echo 'Build inside an aarch64 Linux environment.' >&2
    exit 1
fi

if [ -e "$target_dir" ]; then
    echo "Target already exists: $target_dir. Choose a new directory." >&2
    exit 1
fi

if [ ! -f "$description_dir/users.local.xml" ]; then
    echo 'Create the private login configuration with scripts/configure-user.py first.' >&2
    exit 1
fi

if [ ! -f "$signing_key" ]; then
    echo 'Prepare the VM and download the OBS repository signing key first.' >&2
    exit 1
fi

sudo kiwi-ng --debug --type=oem --profile=Tumbleweed-KDE --color-output \
    system build --description "$description_dir" --target-dir "$target_dir" \
    --signing-key="$signing_key"
