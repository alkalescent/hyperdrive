#!/usr/bin/env python3
"""Generate QR codes for donation addresses from README.md."""

import hashlib
import re
import sys
from io import BytesIO
from pathlib import Path

import qrcode


def parse_addresses(readme: Path) -> dict[str, str]:
    """Parse donation addresses from README.md.

    Looks for backtick-wrapped addresses in the donation table.
    Returns dict mapping currency code to address.
    """
    content = readme.read_text()

    # Match HTML table rows with currency and code-wrapped address
    # Pattern: <td><strong>₿ BTC</strong></td> ... <td><code>address</code></td>
    pattern = (
        r"<td><strong>[₿Ξɱ◈]?\s*(\w+)</strong></td>\s*<td><code>([^<]+)</code></td>"
    )

    addresses = {}
    for match in re.finditer(pattern, content):
        currency = match.group(1).lower()
        address = match.group(2)
        addresses[currency] = address

    return addresses


def generate_qr_image(data: str, output_path: Path) -> bool:
    """Generate a deterministic QR code image.

    Returns True if the file was created/updated, False if unchanged.
    """
    # Create QR code with fixed settings for determinism
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    # Generate image
    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to bytes for comparison
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    new_content = buffer.getvalue()
    new_hash = hashlib.sha256(new_content).hexdigest()

    # Check if file exists and has same content
    if output_path.exists():
        existing_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
        if existing_hash == new_hash:
            return False  # No change needed

    # Write the new image
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(new_content)
    return True


def main() -> None:
    """Main entry point."""
    # Script is in scripts/, repo root is one level up
    repo_root = Path(__file__).parent.parent
    readme = repo_root / "README.md"
    assets_dir = repo_root / "assets"

    if not readme.exists():
        print("ERROR: README.md not found", file=sys.stderr)
        sys.exit(1)

    addresses = parse_addresses(readme)

    if not addresses:
        print("WARNING: No donation addresses found in README.md")
        sys.exit(0)

    print(f"Found {len(addresses)} address(es): {', '.join(addresses.keys())}")

    changes = False
    for currency, address in addresses.items():
        output_path = assets_dir / f"qr_{currency}.png"

        if generate_qr_image(address, output_path):
            print(f"[+] Generated: {output_path}")
            changes = True
        else:
            print(f"[-] Unchanged: {output_path}")

    if changes:
        print("QR codes updated!")
    else:
        print("No changes needed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
