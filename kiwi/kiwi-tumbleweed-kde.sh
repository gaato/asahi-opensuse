#!/bin/sh

set -eu
# KIWI and config.sh must create ordinary system files with normal permissions.
umask 022

description_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
signing_key=${2:-"$description_dir/../.keys/asahi.asc"}

if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != aarch64 ]; then
    echo 'Build inside an aarch64 Linux environment.' >&2
    exit 1
fi

if [ ! -f "$description_dir/users.local.xml" ]; then
    echo 'Create the private login configuration with scripts/configure-user.py first.' >&2
    exit 1
fi

if [ -n "${1-}" ]; then
    target_dir=$1
    build_parent=$(dirname -- "$target_dir")
else
    build_parent="$description_dir/../builds"
    [ -d "$build_parent" ] || mkdir -m 700 -- "$build_parent"
    target_dir="$build_parent/outdir-Tumbleweed-KDE-$(date +%Y%m%d-%H%M%S)"
fi
if [ ! -d "$build_parent" ] || [ "$(stat -c %a -- "$build_parent")" != 700 ]; then
    echo 'The target parent directory must already exist with mode 0700.' >&2
    exit 1
fi
if [ -e "$target_dir" ]; then
    echo "Target already exists: $target_dir. Choose a new directory." >&2
    exit 1
fi

if [ ! -f "$signing_key" ]; then
    echo 'Prepare the VM and download the OBS repository signing key first.' >&2
    exit 1
fi

sudo kiwi-ng --debug --type=oem --profile=Tumbleweed-KDE --color-output \
    system build --description "$description_dir" --target-dir "$target_dir" \
    --signing-key="$signing_key"
