"""Linux integration test of packaging, using temporary files (no block devices)."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/make-installer.py"
spec = importlib.util.spec_from_file_location("packager", SCRIPT)
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class GeometryTests(unittest.TestCase):
    def test_rejects_wrong_sectors_and_layouts(self):
        valid = {"label": "gpt", "unit": "sectors", "sectorsize": 4096,
                 "partitions": [
                     {"start": 256, "size": 100, "type": packager.EFI_TYPE},
                     {"start": 356, "size": 200, "type": sorted(packager.LINUX_TYPES)[0]}]}
        packager.validate_layout(valid, 600 * 4096)
        for update in ({"sectorsize": 512}, {"partitions": valid["partitions"] * 2},
                       {"label": "dos"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                packager.validate_layout(valid | update, 600 * 4096)
        with self.assertRaises(ValueError):
            packager.validate_layout(valid, 500 * 4096)
        valid["partitions"][1]["start"] = 300
        with self.assertRaises(ValueError):
            packager.validate_layout(valid, 600 * 4096)


@unittest.skipUnless(all(shutil.which(tool) for tool in
                        ("sfdisk", "mkfs.vfat", "mkfs.btrfs", "mmd", "mcopy", "blkid", "7z")),
                     "Linux filesystem tools are required")
class PackagingTests(unittest.TestCase):
    def test_real_filesystems_manifest_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="asahi-package-test-") as directory:
            work = Path(directory)

            def run(*args, **kwargs):
                return subprocess.run(args, check=True, capture_output=True, **kwargs)

            image = work / "image with spaces.raw"
            esp = work / "esp.img"
            root = work / "root.img"
            for path, length in ((image, 256 << 20), (esp, 64 << 20), (root, 128 << 20)):
                with path.open("wb") as stream:
                    stream.truncate(length)
            run("sfdisk", "--sector-size", "4096", str(image), text=True,
                input="label: gpt\nunit: sectors\nstart=256,size=16384,type=U\n"
                      "start=16640,size=32768,type=L\n")
            run("mkfs.vfat", "-F", "32", "-i", "A1B2C3D4", str(esp))
            run("mkfs.btrfs", "-f", str(root))
            dummy = work / "dummy"
            dummy.write_bytes(b"packaging fixture only; not a bootable binary\n")
            run("mmd", "-i", str(esp), "::/EFI", "::/EFI/BOOT", "::/m1n1")
            run("mcopy", "-i", str(esp), str(dummy), "::/EFI/BOOT/BOOTAA64.EFI")
            run("mcopy", "-i", str(esp), str(dummy), "::/m1n1/boot.bin")
            with image.open("r+b") as target:
                for source, offset in ((esp, 256 * 4096), (root, 16640 * 4096)):
                    target.seek(offset)
                    with source.open("rb") as stream:
                        shutil.copyfileobj(stream, target)
            output = work / "output with spaces"
            run(sys.executable, str(SCRIPT), str(image), str(output))
            data = json.loads((output / "installer_data.json").read_text())["os_list"][0]
            self.assertEqual([p["name"] for p in data["partitions"]], ["EFI", "Root"])
            self.assertEqual(data["partitions"][0]["volume_id"], "0xa1b2c3d4")
            self.assertEqual(data["partitions"][1]["size"], f"{128 << 20}B")
            archive = output / "os" / data["package"]
            with zipfile.ZipFile(archive) as zipped:
                self.assertNotIn("boot.img", zipped.namelist())
                self.assertEqual(hashlib.sha256(zipped.read("root.img")).digest(),
                                 hashlib.sha256(root.read_bytes()).digest())
            before = archive.read_bytes()
            repeated = subprocess.run([sys.executable, str(SCRIPT), str(image), str(output)],
                                      capture_output=True)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(archive.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
