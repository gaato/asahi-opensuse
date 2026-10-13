"""Static recipe and log-privacy checks; not a substitute for building/booting."""

import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_status", ROOT / "scripts/build-status.py")
build_status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_status)


class RecipeTests(unittest.TestCase):
    def test_bootstrap_selects_intended_providers(self):
        tree = ET.parse(ROOT / "kiwi/config.xml")
        bootstrap = {p.attrib["name"] for p in tree.findall("packages[@type='bootstrap']/package")}
        self.assertTrue({"systemd-default-settings-branding-openSUSE",
                         "systemd-presets-branding-openSUSE", "tar"} <= bootstrap)

    def test_current_codec_provider(self):
        tree = ET.parse(ROOT / "kiwi/config.xml")
        packages = {p.attrib["name"] for p in tree.findall("packages/package")}
        self.assertTrue({"libopenh264-8", "gstreamer-plugins-bad"} <= packages)
        self.assertTrue({"libopenh264-7", "gstreamer-plugin-openh264"}.isdisjoint(packages))

    def test_arm64_efi_and_private_metadata(self):
        tree = ET.parse(ROOT / "kiwi/config.xml")
        packages = {p.attrib["name"] for p in tree.findall("packages/package")}
        self.assertIn("grub2-arm64-efi", packages)
        config = (ROOT / "kiwi/config.sh").read_text()
        self.assertIn("chmod 700 /image", config)
        self.assertIn('chmod 600 "$private_metadata"', config)


class LogPrivacyTests(unittest.TestCase):
    def test_credentials_are_redacted(self):
        for value in ("password=secret", "users.local.xml", "useradd gaato",
                      "pwdformat=sha512", "usermod -p secret"):
            self.assertNotIn(value, build_status.redact(value))
        for algorithm in ("1", "5", "6", "y", "gy"):
            fake = "$" + algorithm + "$example-salt$example-digest"
            self.assertNotIn(fake, build_status.redact("trace " + fake + " end"))
        self.assertEqual(build_status.redact("Retrieving kernel-asahi"),
                         "Retrieving kernel-asahi")


if __name__ == "__main__":
    unittest.main()
