#!/usr/bin/env python3
"""Print build progress while suppressing credential-related log details."""

import argparse
from collections import deque
from pathlib import Path
import re


def redact(line):
    if re.search(r"password|pwdformat|users\.local|useradd|usermod|chpasswd", line, re.I):
        return "[credential-related build detail omitted]\n"
    return re.sub(r"\\?\$(?:1|5|6|y|gy)\\?\$[^\s'\"<>()]+",
                  "[password hash omitted]", line)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--lines", type=int, default=20)
    args = parser.parse_args()
    if args.lines < 1 or args.lines > 200:
        parser.error("Choose between 1 and 200 lines")
    status = args.run / "status"
    print(status.read_text().strip() if status.exists() else "build or packaging in progress")
    for name in ("build.log", "package.log"):
        log = args.run / name
        if log.exists() and log.stat().st_size:
            print(name + ":")
            with log.open(errors="replace") as source:
                for line in deque(source, maxlen=args.lines):
                    print(redact(line), end="")


if __name__ == "__main__":
    main()
