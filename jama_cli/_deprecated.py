"""Stub entry point for the deprecation release of jama-cli."""

import sys

NOTICE = """\
jama-cli has been renamed to 'reqconnect'.

    pip uninstall jama-cli
    pip install reqconnect

See https://github.com/XORwell/reqconnect for details.
"""


def main() -> int:
    sys.stderr.write(NOTICE)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
