#!/bin/bash
# Run as root in the prepared VM; keep personalized artifacts under a private parent.
set -euo pipefail
umask 022
[[ $(uname -s) == Linux && $(uname -m) == aarch64 && $EUID == 0 ]] || {
    echo 'Run as root in the aarch64 build VM.' >&2
    exit 1
}
repo_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
[[ -f "$repo_dir/.vm-prepared" ]] || { echo 'Prepare the VM first.' >&2; exit 1; }
owner=${SUDO_USER:-gaato}
id "$owner" >/dev/null
build_parent="$repo_dir/builds"
[[ -d "$build_parent" && $(stat -c %a "$build_parent") == 700 ]] || {
    echo 'Create the private builds directory with mode 0700 first.' >&2
    exit 1
}
run_dir=$(mktemp -d "$build_parent/run-XXXXXXXX")
chown "$owner:" "$run_dir"
for name in build.log package.log; do
    touch "$run_dir/$name"
    chmod 600 "$run_dir/$name"
    chown "$owner:" "$run_dir/$name"
done
echo "Build run: $run_dir"

set +e
sh "$repo_dir/kiwi/kiwi-tumbleweed-kde.sh" "$run_dir/image" > "$run_dir/build.log" 2>&1
build_status=$?
set -e
if [[ $build_status != 0 ]]; then
    printf 'build failed (exit %s)\n' "$build_status" > "$run_dir/status"
    exit "$build_status"
fi
shopt -s nullglob
images=("$run_dir/image"/*.raw)
[[ ${#images[@]} == 1 ]] || {
    echo 'Expected exactly one raw image.' > "$run_dir/status"
    exit 1
}
set +e
python3 "$repo_dir/scripts/make-installer.py" "${images[0]}" "$run_dir/installer" \
    > "$run_dir/package.log" 2>&1
package_status=$?
set -e
if [[ $package_status != 0 ]]; then
    printf 'packaging failed (exit %s)\n' "$package_status" > "$run_dir/status"
    exit "$package_status"
fi
chown "$owner:" "$run_dir/installer"
echo 'build and packaging complete' > "$run_dir/status"
echo "Installer artifacts: $run_dir/installer"
