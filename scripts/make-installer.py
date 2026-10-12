#!/usr/bin/env python3
"""Package a 4096-byte-sector KIWI EFI + Btrfs image for Asahi Installer."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

SECTOR_SIZE = 4096
EFI_TYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
LINUX_TYPES = {"0fc63daf-8483-4772-8e79-3d69d8477de4",
               "b921b045-1df0-41c3-af44-4c6f280d3fae"}
PACKAGE = "Tumbleweed-KDE.zip"


def run(*command):
    return subprocess.run(command, check=True, text=True, capture_output=True).stdout.strip()


def validate_layout(table, image_size):
    if table.get("label") != "gpt" or table.get("unit") != "sectors":
        raise ValueError("Expected a GPT image with sector-based offsets")
    if table.get("sectorsize") != SECTOR_SIZE:
        raise ValueError("Expected 4096-byte sectors for Apple Silicon")
    parts = table.get("partitions", [])
    if len(parts) != 2:
        raise ValueError("Expected exactly two partitions: EFI and Btrfs root")
    if parts[0].get("type", "").lower() != EFI_TYPE:
        raise ValueError("The first partition must be an EFI System Partition")
    if parts[1].get("type", "").lower() not in LINUX_TYPES:
        raise ValueError("The second partition must be a Linux root/filesystem partition")
    end = 2 * SECTOR_SIZE
    for part in parts:
        start, size = part.get("start"), part.get("size")
        if type(start) is not int or type(size) is not int or size <= 0:
            raise ValueError("Invalid partition geometry")
        offset, length = start * SECTOR_SIZE, size * SECTOR_SIZE
        if offset < end or offset + length > image_size:
            raise ValueError("Partition overlaps another partition or exceeds the image")
        end = offset + length
    return parts


def copy_partition(image, part, destination):
    remaining = part["size"] * SECTOR_SIZE
    with image.open("rb") as source, destination.open("xb") as output:
        source.seek(part["start"] * SECTOR_SIZE)
        while remaining:
            block = source.read(min(8 * 1024 * 1024, remaining))
            if not block:
                raise ValueError("Unexpected end of raw image")
            output.write(block)
            remaining -= len(block)


def manifest(esp_size, root_size, volume_id):
    return {"os_list": [{
        "name": "openSUSE Tumbleweed KDE",
        "default_os_name": "openSUSE Tumbleweed",
        "boot_object": "m1n1.bin", "next_object": "m1n1/boot.bin",
        "package": PACKAGE,
        "supported_fw": ["12.3", "12.3.1", "13.5"],
        "partitions": [
            {"name": "EFI", "type": "EFI", "size": f"{esp_size}B",
             "format": "fat", "volume_id": volume_id, "source": "esp",
             "copy_firmware": True, "copy_installer_data": True},
            {"name": "Root", "type": "Linux", "size": f"{root_size}B",
             "expand": True, "image": "root.img"},
        ],
    }]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("output", type=Path, nargs="?", default=Path("installer-output"))
    args = parser.parse_args()
    image = args.image.resolve(strict=True)
    if not stat.S_ISREG(image.stat().st_mode):
        parser.error("Input must be a regular raw image file, not a device")
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        parser.error("Output already exists; choose a new directory")
    for tool in ("sfdisk", "blkid", "7z"):
        if not shutil.which(tool):
            parser.error(f"Required command not found: {tool}")
    table = json.loads(run("sfdisk", "--json", "--sector-size", str(SECTOR_SIZE),
                           str(image)))["partitiontable"]
    parts = validate_layout(table, image.stat().st_size)
    # Staging is private because the root image contains login password hashes.
    with tempfile.TemporaryDirectory(prefix="asahi-package-", dir=output.parent) as temporary:
        work = Path(temporary)
        package_dir = work / "contents"
        package_dir.mkdir()
        esp_image = work / "esp.img"
        root_image = package_dir / "root.img"
        copy_partition(image, parts[0], esp_image)
        copy_partition(image, parts[1], root_image)
        if run("blkid", "-p", "-s", "TYPE", "-o", "value", str(esp_image)) != "vfat":
            raise ValueError("EFI partition is not FAT")
        if run("blkid", "-p", "-s", "TYPE", "-o", "value", str(root_image)) != "btrfs":
            raise ValueError("Root partition is not Btrfs")
        uuid = run("blkid", "-p", "-s", "UUID", "-o", "value", str(esp_image))
        if not re.fullmatch(r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}", uuid):
            raise ValueError("Unexpected FAT volume ID")
        esp = package_dir / "esp"
        run("7z", "x", "-y", f"-o{esp}", str(esp_image))
        for path in (esp / "m1n1/boot.bin", esp / "EFI/BOOT/BOOTAA64.EFI"):
            if not path.is_file() or not path.stat().st_size:
                raise ValueError(f"Missing boot artifact: {path.relative_to(esp)}")
        for path in esp.rglob("*"):
            if path.is_symlink():
                raise ValueError("Unexpected symlink in EFI partition")
        staged = work / "result"
        (staged / "os").mkdir(parents=True)
        archive = staged / "os" / PACKAGE
        subprocess.run(["7z", "a", "-tzip", "-mx=3", str(archive), "esp", "root.img"],
                       cwd=package_dir, check=True, stdout=subprocess.DEVNULL)
        with zipfile.ZipFile(archive) as zipped:
            if zipped.getinfo("root.img").file_size != root_image.stat().st_size:
                raise ValueError("ZIP root image size mismatch")
            damaged = zipped.testzip()
            if damaged:
                raise ValueError(f"ZIP integrity check failed: {damaged}")
        data = manifest(esp_image.stat().st_size, root_image.stat().st_size,
                        "0x" + uuid.replace("-", "").lower())
        (staged / "installer_data.json").write_text(json.dumps(data, indent=2) + "\n")
        with archive.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        (staged / "SHA256SUMS").write_text(f"{checksum}  os/{PACKAGE}\n")
        staged.chmod(0o700)
        staged.rename(output)
    print(f"Installer artifacts: {output}")
    print("Use this directory as the Asahi installer's REPO_BASE; copy installer_data.json")
    print("into its working directory. The personalized ZIP must remain private.")


if __name__ == "__main__":
    main()
