#!/bin/bash
# Run as root inside the dedicated aarch64 openSUSE build VM.
set -euo pipefail
umask 077

[[ $(uname -s) == Linux && $(uname -m) == aarch64 && $EUID == 0 ]] || {
    echo 'Run as root inside the aarch64 openSUSE VM.' >&2
    exit 1
}
repo_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
zypper -n install python3-kiwi python3-base createrepo_c git-core 7zip wget file \
    util-linux dosfstools btrfsprogs e2fsprogs gptfdisk qemu-tools curl gpg2

# Serial SSH/UTM input already arrives as characters; configure physical input
# independently and avoid localectl's approximate console/XKB conversion.
localectl --no-convert set-keymap jp-dvorak
localectl --no-convert set-x11-keymap jp apple dvorak

if [[ ! -f "$repo_dir/kiwi/users.local.xml" ]]; then
    # Reuse the VM user's existing hash only after the owner's explicit consent.
    python3 "$repo_dir/scripts/configure-user.py" gaato --from-local-user
fi
mkdir -p "$repo_dir/.keys"
if ! curl --fail --location --silent --show-error \
    https://download.opensuse.org/repositories/home:/gaato:/asahi/openSUSE_Factory_ARM/repodata/repomd.xml.key \
    --output "$repo_dir/.keys/asahi.asc"; then
    # A new subproject inherits home:gaato's signing key before first publication.
    curl --fail --location --silent --show-error \
        https://api.opensuse.org/public/source/home:gaato/_pubkey \
        --output "$repo_dir/.keys/asahi.asc"
fi
fingerprint=$(gpg --show-keys --with-colons "$repo_dir/.keys/asahi.asc" | awk -F: '$1 == "fpr" {print $10; exit}')
[[ "$fingerprint" == D77B53A88D13FCF52DB74708FD5BA6D81CE88118 ]] || {
    echo 'OBS signing key changed; verify its fingerprint before building.' >&2
    exit 1
}
echo "OBS signing key fingerprint: $fingerprint"

# Validate the XML/schema without printing the private user include.
kiwi-ng --profile=Tumbleweed-KDE image info --description="$repo_dir/kiwi" --list-profiles
touch "$repo_dir/.vm-prepared"
echo 'VM preparation complete.'
