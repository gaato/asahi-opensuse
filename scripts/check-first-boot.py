#!/usr/bin/env python3
"""Read-only first-boot evidence. Does not play audio or change configuration."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess


def command(*args):
    if not shutil.which(args[0]):
        return None
    result = subprocess.run(args, text=True, capture_output=True, timeout=20)
    return result.stdout.strip() if result.returncode == 0 else None


def report(ok, label):
    print(("PASS: " if ok else "CHECK: ") + label)
    return bool(ok)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-uuid")
    parser.add_argument("--efi-uuid")
    args = parser.parse_args()
    os.environ["LC_ALL"] = "C"
    os.environ["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    compatible = Path("/proc/device-tree/compatible")
    if not compatible.is_file() or b"apple,j313" not in compatible.read_bytes():
        print("STOP: this check is for the physical M1 MacBook Air, not the builder VM")
        return 2
    results = []
    kernel = command("uname", "-r") or "unknown"
    print("Kernel:", kernel)
    results.append(report("asahi" in kernel, "running Asahi kernel"))
    results.append(report(command("getconf", "PAGESIZE") == "16384", "running with 16K pages"))
    results.append(report(command("getenforce") == "Enforcing", "SELinux enforcing at runtime"))
    results.append(report(command("findmnt", "-n", "-o", "FSTYPE", "/") == "btrfs", "root is Btrfs"))
    for mountpoint, expected in (("/", args.root_uuid), ("/boot/efi", args.efi_uuid)):
        actual = command("findmnt", "-n", "-o", "UUID", mountpoint)
        results.append(report(bool(actual) and (expected is None or actual.lower() == expected.lower()), "mounted filesystem UUID: " + mountpoint))
    results.append(report(Path("/boot/efi/vendorfw/firmware.cpio").is_file(), "installer copied vendor firmware archive"))
    for service in ("NetworkManager", "display-manager", "speakersafetyd"):
        results.append(report(command("systemctl", "is-active", service + ".service") == "active", "active system service: " + service))
    consoles = Path("/etc/vconsole.conf")
    results.append(report(consoles.is_file() and "KEYMAP=us-dvorak" in consoles.read_text().replace('"', ''), "standard US Dvorak console"))
    drm_drivers = [p.resolve().name for p in Path("/sys/class/drm").glob("card[0-9]*/device/driver")]
    results.append(report("asahi" in drm_drivers, "Asahi GPU driver bound to a DRM device"))
    sessions = command("loginctl", "list-sessions", "--no-legend") or ""
    graphical = False
    for line in sessions.splitlines():
        fields = line.split()
        if not fields:
            continue
        details = command("loginctl", "show-session", fields[0], "-p", "Name", "-p", "Active", "-p", "Type") or ""
        if all(value in details.splitlines() for value in ("Name=gaato", "Active=yes", "Type=wayland")):
            graphical = True
    results.append(report(graphical, "gaato has an active Wayland login session"))
    results.append(report(command("pgrep", "-u", "gaato", "-x", "plasmashell") is not None, "Plasma shell process running for gaato"))
    state = command("nmcli", "-t", "-f", "STATE", "general") or ""
    results.append(report(state.startswith("connected"), "NetworkManager reports a connected network (SSID/address withheld)"))
    if os.geteuid() == 0:
        print("CHECK: run as gaato inside Plasma too, to inspect user audio services")
        results.append(False)
    else:
        for service in ("pipewire", "wireplumber"):
            results.append(report(command("systemctl", "--user", "is-active", service + ".service") == "active", "active user service: " + service))
    print("No sound played. Before speaker playback, separately verify DSP routing, safety logs and absence of bypass parameters.")
    print("Still requires human checks: visible desktop, JIS/Dvorak punctuation, password login, real network reachability and speaker behavior.")
    print("This report is evidence for individual checks, not a declaration that migration is complete.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
