"""Check that a build holds only the sdist and wheel of the release version.

hatch-vcs reads the version from the git tag at build time. A build from an
untagged commit gets a dev version instead, so its files do not match and the
release stops before it publishes.
"""

import argparse
from pathlib import Path

NAME = "hyperdrive"


def main(argv: list[str] | None = None) -> int:
    """Compare the built files with the files the release version needs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="PyPI version, such as 1.6.0")
    parser.add_argument("dist", nargs="?", default="dist", help="build directory")
    args = parser.parse_args(argv)

    expected = {
        f"{NAME}-{args.version}.tar.gz",
        f"{NAME}-{args.version}-py3-none-any.whl",
    }
    dist = Path(args.dist)
    paths = dist.iterdir() if dist.is_dir() else []
    # uv build writes a .gitignore into the build directory.
    found = {path.name for path in paths if not path.name.startswith(".")}
    print(f"Expected: {', '.join(sorted(expected))}")
    print(f"Found: {', '.join(sorted(found)) or 'nothing'}")
    if found == expected:
        return 0
    print(f"{dist} does not hold exactly the {args.version} release files")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
