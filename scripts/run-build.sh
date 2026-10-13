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
resume_option=
if [[ $# == 2 && $1 == --resume ]]; then
    run_dir=$(realpath -e -- "$2")
    [[ $run_dir == "$build_parent"/run-* && ${run_dir#"$build_parent"/} != */* ]] || {
        echo 'Resume must target a run directly inside this private builds directory.' >&2
        exit 1
    }
    [[ $(stat -c %a "$run_dir") == 700 && -f "$run_dir/status" &&
       $(<"$run_dir/status") == 'build failed'* &&
       -d "$run_dir/image/build/image-root" && ! -e "$run_dir/installer" ]] || {
        echo 'Resume requires a failed preparation run, not completed artifacts.' >&2
        exit 1
    }
    if compgen -G "$run_dir/image/*.raw" > /dev/null; then
        echo 'A raw image already exists; use a fresh run.' >&2
        exit 1
    fi
    archive_dir=$(mktemp -d "$run_dir/failed-attempt-XXXXXXXX")
    chown "$owner:" "$archive_dir"
    for name in build.log package.log status; do
        [[ ! -f "$run_dir/$name" ]] || mv -- "$run_dir/$name" "$archive_dir/$name"
    done
    echo "Previous failed logs: $archive_dir"
    echo 'Resume is only safe when the XML/profile/layout has not changed.'
    resume_option=--resume
elif [[ $# == 0 ]]; then
    run_dir=$(mktemp -d "$build_parent/run-XXXXXXXX")
else
    echo 'Usage: run-build.sh [--resume PRIVATE_RUN_DIRECTORY]' >&2
    exit 1
fi
chown "$owner:" "$run_dir"
for name in build.log package.log; do
    touch "$run_dir/$name"
    chmod 600 "$run_dir/$name"
    chown "$owner:" "$run_dir/$name"
done
echo "Build run: $run_dir"

set +e
sh "$repo_dir/kiwi/kiwi-tumbleweed-kde.sh" "$run_dir/image" \
    "$repo_dir/.keys/asahi.asc" ${resume_option:+"$resume_option"} > "$run_dir/build.log" 2>&1
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
