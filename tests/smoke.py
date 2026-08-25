#!/usr/bin/env python3
"""Smoke tests for verifying package installation and imports.

Prerequisites:
    The package must be installed (e.g., `uv sync` or `pip install hyperdrive`)
    before running these tests.

Usage:
    python tests/smoke.py
"""

import importlib
import sys
import tomllib
from pathlib import Path


def get_package_name() -> str:
    """Get package name from pyproject.toml."""
    current_path = Path(__file__).resolve().parent
    while current_path != current_path.parent:
        pyproject_path = current_path / "pyproject.toml"
        if pyproject_path.exists():
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            return data["project"]["name"]
        current_path = current_path.parent
    raise RuntimeError("Could not find pyproject.toml in parent directories.")


def test_imports() -> None:
    """Test package imports work correctly."""
    package = get_package_name()

    # Test main package import
    pkg = importlib.import_module(package)
    assert hasattr(pkg, "__version__"), "Package should have __version__"
    print(f"[+] {package}.__version__ = {pkg.__version__}")

    # Test core module imports
    core_modules = [
        "DataSource",
        "Exchange",
        "History",
        "Precognition",
        "Storage",
        "Broker",
        "Constants",
    ]

    for module_name in core_modules:
        try:
            importlib.import_module(f"{package}.{module_name}")
            print(f"[+] {package}.{module_name}")
        except ImportError as e:
            print(f"[-] {package}.{module_name}: {e}", file=sys.stderr)
            raise


def test_core_classes() -> None:
    """Test that core classes are importable."""
    package = get_package_name()

    # Import core classes that should be available
    classes_to_test = [
        ("DataSource", "Polygon"),
        ("DataSource", "MarketData"),
        ("Exchange", "Binance"),
        ("History", "Historian"),
        ("Storage", "Store"),
    ]

    for module_name, class_name in classes_to_test:
        try:
            module = importlib.import_module(f"{package}.{module_name}")
            assert hasattr(module, class_name), (
                f"{module_name} should have {class_name}"
            )
            print(f"[+] {package}.{module_name}.{class_name}")
        except (ImportError, AssertionError) as e:
            print(f"[-] {package}.{module_name}.{class_name}: {e}", file=sys.stderr)
            raise


def main() -> None:
    """Run smoke tests."""
    package = get_package_name()
    print(f"Running smoke tests for: {package}")

    try:
        test_imports()
        test_core_classes()
        print("\nAll smoke tests passed!")
    except (ImportError, AssertionError) as e:
        print(f"\nSmoke test failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
