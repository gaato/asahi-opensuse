#!/usr/bin/env python3
"""Create a private KIWI user include; never print passwords or hashes."""

import argparse
import getpass
import os
from pathlib import Path
import pwd
import re
import subprocess
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--from-local-user", action="store_true",
                        help="Reuse this Linux account's hash; requires root and explicit consent")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "kiwi/users.local.xml")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", args.username) or args.username == "root":
        parser.error("Choose a non-root Linux username (lowercase letters, digits, _ or -).")
    if args.output.exists():
        parser.error("The private include already exists. It will not be overwritten.")

    if args.from_local_user:
        pwd.getpwnam(args.username)
        with open("/etc/shadow", encoding="utf-8") as source:
            hashes = {row.split(":", 2)[0]: row.split(":", 2)[1] for row in source}
        password_hash = hashes.get(args.username, "")
        if not password_hash.startswith(("$6$", "$y$", "$gy$")):
            parser.error("The local account must have an unlocked SHA-512 or yescrypt password.")
    else:
        password = getpass.getpass("Password for the installed system: ")
        if not password or "\n" in password or "\r" in password:
            parser.error("A nonempty, single-line password is required.")
        if password != getpass.getpass("Confirm password: "):
            parser.error("Passwords did not match.")
        password_hash = subprocess.run(
            ["openssl", "passwd", "-6", "-stdin"], input=password + "\n",
            text=True, capture_output=True, check=True).stdout.strip()
        del password
        if not password_hash.startswith("$6$"):
            parser.error("Password hashing failed.")

    image = ET.Element("image")
    users = ET.SubElement(image, "users")
    ET.SubElement(users, "user", name="root", home="/root", groups="root",
                  pwdformat="encrypted", password="!")
    ET.SubElement(users, "user", name=args.username, home="/home/" + args.username,
                  groups="users,wheel", pwdformat="encrypted", password=password_hash)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        ET.ElementTree(image).write(output, encoding="utf-8", xml_declaration=True)
    print(f"Private login configuration created: {args.output}")
    print("Keep this file, build logs, and personalized images out of public repositories.")


if __name__ == "__main__":
    main()
