#!/usr/bin/env python3
"""One-time setup: generates VAPID keys and app icons."""
import json
import base64
from pathlib import Path


def generate_vapid_keys():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    private_key = ec.generate_private_key(ec.SECP256R1())

    # Raw private key (32 bytes) -> base64url
    private_numbers = private_key.private_numbers()
    private_bytes = private_numbers.private_value.to_bytes(32, "big")
    private_b64 = base64.urlsafe_b64encode(private_bytes).decode().rstrip("=")

    # Raw public key (65 bytes, uncompressed point) -> base64url
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    public_b64 = base64.urlsafe_b64encode(public_bytes).decode().rstrip("=")

    return {"privateKey": private_b64, "publicKey": public_b64}


def generate_icons():
    from PIL import Image, ImageDraw, ImageFont

    static_dir = Path("static")
    static_dir.mkdir(exist_ok=True)

    for size in [192, 512]:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Rounded purple background
        radius = size // 5
        draw.rounded_rectangle(
            [0, 0, size - 1, size - 1], radius=radius, fill="#6C5CE7"
        )

        # White "C" letter
        font_size = int(size * 0.45)
        font = None
        for font_name in ["arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf"]:
            try:
                font = ImageFont.truetype(font_name, font_size)
                break
            except OSError:
                continue
        if font is None:
            try:
                font = ImageFont.load_default(size=font_size)
            except TypeError:
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), "C", font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (size - tw) / 2 - bbox[0]
        y = (size - th) / 2 - bbox[1]
        draw.text((x, y), "C", fill="white", font=font)

        out = static_dir / f"icon-{size}.png"
        img.save(out, "PNG")
        print(f"  Created {out}")


def main():
    keys_file = Path("vapid_keys.json")
    if keys_file.exists():
        print(f"VAPID keys already exist ({keys_file}), skipping.")
    else:
        keys = generate_vapid_keys()
        keys_file.write_text(json.dumps(keys, indent=2))
        print(f"Generated VAPID keys -> {keys_file}")
        print(f"  Public key:  {keys['publicKey'][:40]}...")

    print("Generating icons...")
    generate_icons()

    print("\nSetup complete!")
    print("Run:  uvicorn server:app --host 0.0.0.0 --port 8080")


if __name__ == "__main__":
    main()
