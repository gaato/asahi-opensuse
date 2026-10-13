#!/usr/bin/env python3
"""Read-only audit of a personalized Asahi image; never print credentials."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
import zlib


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        print("Command failed:", args[0], "exit", result.returncode, flush=True)
        if args[0] in ("mount", "umount", "losetup"):
            print(result.stderr.strip(), flush=True)
        result.check_returncode()
    return result.stdout.strip()


def check(condition, message):
    if not condition:
        raise ValueError(message)
    print("PASS:", message, flush=True)


def read(path):
    return path.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("installer", type=Path)
    parser.add_argument("private_users", type=Path)
    args = parser.parse_args()
    check(os.geteuid() == 0, "audit runs as root")
    raw = args.image.resolve(strict=True)
    check(stat.S_ISREG(raw.stat().st_mode), "input is a regular file, not a physical device")
    spec = importlib.util.spec_from_file_location("packager", Path(__file__).with_name("make-installer.py"))
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)
    table = json.loads(run("sfdisk", "--json", "--sector-size", "4096", str(raw)))["partitiontable"]
    parts = packager.validate_layout(table, raw.stat().st_size)
    check(len(parts) == 2, "4096-byte GPT layout: EFI plus root")
    loop = run("losetup", "--find", "--show", "--read-only", "--sector-size", "4096", "--partscan", str(raw))
    mounted = []
    temporary = tempfile.TemporaryDirectory(prefix="audit-", dir=raw.parent.parent)
    try:
        work = Path(temporary.name)
        root, esp, top = (work / name for name in ("root", "esp", "top"))
        for path in (root, esp, top):
            path.mkdir()
        run("mount", "-o", "ro,rescue=nologreplay", loop + "p2", str(root))
        mounted.append(root)
        run("mount", "-o", "ro", loop + "p1", str(esp))
        mounted.append(esp)
        run("mount", "-o", "ro,rescue=nologreplay,subvolid=5", loop + "p2", str(top))
        mounted.append(top)
        root_uuid = run("blkid", "-s", "UUID", "-o", "value", loop + "p2")
        esp_uuid = run("blkid", "-s", "UUID", "-o", "value", loop + "p1")
        print("Root UUID:", root_uuid, "EFI UUID:", esp_uuid, flush=True)
        fstab = read(root / "etc/fstab")
        entries = [line.split() for line in fstab.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        check(any(e[0] == "UUID=" + root_uuid and e[1] == "/" for e in entries), "fstab root matches actual Btrfs UUID")
        check(any(e[0] == "UUID=" + esp_uuid and e[1] == "/boot/efi" for e in entries), "fstab EFI matches actual FAT UUID")
        check(all(not e[0].startswith("UUID=") or e[0][5:] in (root_uuid, esp_uuid) for e in entries), "all fstab filesystem UUIDs remain valid after GPT replacement")
        data = json.loads(read(args.installer / "installer_data.json"))["os_list"][0]
        check(data["partitions"][0]["volume_id"].lower() == "0x" + esp_uuid.replace("-", "").lower(), "installer preserves FAT volume ID")
        check(int(data["partitions"][1]["size"][:-1]) == parts[1]["size"] * 4096, "installer root size matches raw partition")
        efi_files = {str(p.relative_to(esp)).casefold(): p for p in esp.rglob("*") if p.is_file()}
        print("EFI files:", ", ".join(sorted(efi_files)), flush=True)
        for name in ("efi/boot/bootaa64.efi", "efi/boot/grub.efi", "efi/boot/mokmanager.efi", "m1n1/boot.bin"):
            check(name in efi_files and efi_files[name].stat().st_size > 0, "boot artifact present: " + name)
        for name in ("efi/boot/bootaa64.efi", "efi/boot/grub.efi"):
            content = efi_files[name].read_bytes()
            offset = int.from_bytes(content[60:64], "little")
            check(content[:2] == b"MZ" and content[offset:offset+6] == b"PE\0\0\x64\xaa", "AArch64 PE binary: " + name)
        grub = read(root / "boot/grub2/grub.cfg")
        check(root_uuid in grub and "root=UUID=" + root_uuid in grub, "GRUB locates kernel and root by preserved filesystem UUID")
        check("root=PARTUUID=" not in grub, "GRUB does not depend on replaced GPT partition UUID")
        check(root_uuid in read(efi_files["efi/boot/grub.cfg"]), "EFI GRUB trampoline locates root by filesystem UUID")
        boot_bin = efi_files["m1n1/boot.bin"].read_bytes()
        check(b"apple,j313" in boot_bin, "stage2 contains M1 Air device tree")
        compressed_uboot = False
        for match in re.finditer(b"\x1f\x8b\x08", boot_bin):
            try:
                payload = zlib.decompress(boot_bin[match.start():], wbits=31)
                if b"U-Boot" in payload:
                    compressed_uboot = True
                    break
            except zlib.error:
                continue
        check(compressed_uboot, "stage2 contains a valid gzip-compressed U-Boot payload")
        kernels = run("rpm", "--root", str(root), "-qa", "--qf", "%{NAME} %{VERSION}-%{RELEASE}\n")
        kernel_packages = [line for line in kernels.splitlines() if re.match(r"kernel-(asahi|default|vanilla|desktop) ", line)]
        check(len(kernel_packages) == 1 and kernel_packages[0].startswith("kernel-asahi "), "only Asahi kernel installed")
        version = kernel_packages[0].split()[1] + "-asahi"
        print("Kernel:", version, flush=True)
        check("dtb-apple " + kernel_packages[0].split()[1] in kernels.splitlines(), "DTB package version matches Asahi kernel")
        check(os.readlink(root / "boot/dtb").rstrip("/").endswith("dtb-" + version), "boot DTB symlink matches Asahi kernel")
        kernel_lines = [line for line in grub.splitlines() if "root=UUID=" in line]
        print("Kernel command lines:", " | ".join(line.strip() for line in kernel_lines), flush=True)
        normal_entries = [line for line in kernel_lines if "single" not in line.split()]
        check(bool(normal_entries) and all("security=selinux" in line for line in normal_entries), "GRUB explicitly selects SELinux for all normal boot entries")
        check(all(not re.search(r"\b(rd\.break|init=/bin/(ba)?sh|selinux=0|enforcing=0)\b", line) for line in kernel_lines), "kernel entries have no security bypass or debug shell arguments")
        modprobe_files = list((root / "etc/modprobe.d").glob("*.conf")) + list((root / "usr/lib/modprobe.d").glob("*.conf"))
        check("please_blow_up_my_speakers" not in grub and all("please_blow_up_my_speakers" not in read(p) for p in modprobe_files), "speaker safety bypass absent from GRUB and modprobe configs")
        config = read(root / ("boot/config-" + version))
        for option in ("CONFIG_ARM64_16K_PAGES=y", "CONFIG_SECURITY_SELINUX=y", "CONFIG_DRM_ASAHI=m", "CONFIG_NVME_APPLE=m", "CONFIG_APPLE_DART=m", "CONFIG_BRCMFMAC=m", "CONFIG_SND_SOC_APPLE_MCA=m"):
            check(option in config.splitlines(), "kernel " + option)
        # Absolute guest symlinks must not be followed into the builder host.
        check((root / ("usr/lib/modules/" + version + "/Image")).is_file(), "matching Asahi kernel Image present")
        initrd = root / ("boot/initrd-" + version)
        modules = run("lsinitrd", "-m", str(initrd))
        for module in ("asahi-firmware", "kernel-modules-asahi", "btrfs"):
            check(module in [line.strip() for line in modules.splitlines()], "initrd module " + module)
        listing = run("lsinitrd", str(initrd))
        for filename in ("load-asahi-firmware.sh", "install-asahi-firmware.sh", "nvme-apple", "apple-dart"):
            check(filename in listing or filename.replace("-", "_") in listing, "initrd includes " + filename)
        check(not (root / "boot/.builder").exists(), "builder boot marker removed")
        check("SELINUX=enforcing" in read(root / "etc/selinux/config"), "image SELinux configured enforcing")
        label = os.getxattr(root / "etc/shadow", "security.selinux").decode().rstrip("\0")
        check(":shadow_t:" in label, "shadow SELinux label retained")
        check(stat.S_IMODE((root / "etc/shadow").stat().st_mode) & 0o007 == 0, "shadow not readable by other users")
        shadow_backup = root / "etc/shadow-"
        check(not shadow_backup.exists() or shadow_backup.stat().st_mode & 0o007 == 0, "shadow backup not readable by other users")
        shadow = {row.split(":")[0]: row.split(":")[1] for row in read(root / "etc/shadow").splitlines()}
        private = ET.parse(args.private_users).getroot()
        gaato = next(e for e in private.iter("user") if e.attrib.get("name") == "gaato")
        check(shadow.get("gaato") == gaato.attrib["password"], "gaato hash matches private approved VM credentials (not displayed)")
        check(shadow.get("root", "").startswith(("!", "*")), "root direct password login locked")
        groups = read(root / "etc/group").splitlines()
        check(any(row.startswith("wheel:") and "gaato" in row.split(":")[-1].split(",") for row in groups), "gaato is in wheel")
        for filename in (".profile", ".kconfig", "image/config.xml"):
            path = root / filename
            check(not path.exists() or path.stat().st_mode & 0o077 == 0, "private KIWI metadata absent or protected: " + filename)
        check(not (root / "image").exists() or (root / "image").stat().st_mode & 0o077 == 0, "entire KIWI metadata directory absent or private")
        check(not (root / "etc/machine-id").exists() or not read(root / "etc/machine-id").strip(), "machine ID generated at first boot")
        check(not (top / "@/var/lib/systemd/random-seed").exists(), "no cloned systemd random seed")
        check(not list((root / "etc/ssh").glob("ssh_host_*")), "SSH host keys generated per installation")
        check(not (top / "@/home/gaato/.ssh/authorized_keys").exists(), "no unapproved persistent SSH credential injected into real image")
        check("KEYMAP=us-dvorak" in read(root / "etc/vconsole.conf").replace('"', ''), "console uses standard US Dvorak")
        keymap = read(root / "etc/X11/xorg.conf.d/00-keyboard.conf")
        check('"dvorak"' in keymap and '"us"' in keymap, "XKB uses US Dvorak")
        print("Home subvolumes:", ", ".join(str(p.relative_to(top)) for p in top.glob("@/home/*")), flush=True)
        for path in (root / "etc/skel/.config/kxkbrc", top / "@/home/gaato/.config/kxkbrc", root / "var/lib/sddm/.config/kxkbrc"):
            # /var is a separate subvolume in the final image.
            if str(path).startswith(str(root / "var")):
                path = top / "@/var/lib/sddm/.config/kxkbrc"
            check(path.is_file() and "VariantList=dvorak" in read(path), "Dvorak desktop configuration: " + str(path.relative_to(work)))
        check("DisplayServer=wayland" in read(root / "etc/sddm.conf.d/10-wayland-default.conf"), "SDDM uses Wayland")
        for service in ("NetworkManager", "chronyd", "speakersafetyd"):
            enabled = list((root / "etc/systemd/system").glob("*.wants/" + service + ".service"))
            check(bool(enabled), "enabled service " + service)
        check(os.readlink(root / "etc/systemd/system/display-manager.service").endswith("/sddm.service"), "display-manager alias points to SDDM")
        for package in ("libopenh264-8", "speakersafetyd", "asahi-audio", "asahi-fwupdate", "update-m1n1", "dtb-apple", "grub2-arm64-efi", "sudo-policy-wheel-auth-self"):
            found = [line for line in kernels.splitlines() if line.startswith(package + " ")]
            check(bool(found), "package installed: " + package)
            print("Version:", found[0], flush=True)
        models = list((root / "usr/share/speakersafetyd").rglob("*j313*"))
        check(bool(models), "speaker safety model data for M1 MacBook Air j313")
        audio_files = run("rpm", "--root", str(root), "-ql", "asahi-audio").splitlines()
        print("Audio configuration files:", ", ".join(p for p in audio_files if "wireplumber" in p or "j313" in p), flush=True)
        check(any("wireplumber" in p and p.endswith(".conf") and (root / p.lstrip("/")).is_file() for p in audio_files), "Asahi WirePlumber routing configuration installed")
        check(any("j313" in p and (root / p.lstrip("/")).is_file() for p in audio_files), "Asahi audio configuration for j313 installed")
        expected, name = read(args.installer / "SHA256SUMS").strip().split()
        check(name == "os/Tumbleweed-KDE.zip", "checksum names expected private ZIP")
        with (args.installer / name).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        check(actual == expected, "packaged ZIP SHA256 matches manifest")
        with zipfile.ZipFile(args.installer / name) as zipped:
            check(zipped.getinfo("root.img").file_size == parts[1]["size"] * 4096, "ZIP root image length matches partition")
            remaining = parts[1]["size"] * 4096
            with zipped.open("root.img") as packaged, raw.open("rb") as original:
                original.seek(parts[1]["start"] * 4096)
                while remaining:
                    size = min(8 * 1024 * 1024, remaining)
                    if packaged.read(size) != original.read(size):
                        raise ValueError("ZIP root bytes differ from audited raw partition")
                    remaining -= size
            check(True, "ZIP root bytes exactly match audited raw partition")
            zip_files = {p.casefold(): p for p in zipped.namelist()}
            for relative, path in efi_files.items():
                member = zip_files.get("esp/" + relative)
                check(member is not None and zipped.read(member) == path.read_bytes(), "ZIP boot file matches audited ESP: " + relative)
        print("AUDIT COMPLETE: read-only static image checks passed; physical boot remains unverified", flush=True)
    finally:
        for mount in reversed(mounted):
            run("umount", str(mount))
        run("losetup", "--detach", loop)
        temporary.cleanup()


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print("AUDIT FAILED:", error, flush=True)
        raise SystemExit(1)
    except Exception as error:
        # Do not expose command stderr or arbitrary file content from this image.
        print("AUDIT FAILED:", type(error).__name__, "(details withheld to protect credentials)", flush=True)
        raise SystemExit(1)
