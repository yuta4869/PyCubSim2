#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Windows and Linux icons from the PyCubSim2 PNG."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--ico", type=Path)
    parser.add_argument("--png", type=Path)
    parser.add_argument("--png-size", type=int, default=512)
    args = parser.parse_args()
    if args.ico is None and args.png is None:
        parser.error("At least one of --ico or --png is required.")
    if args.png_size < 16:
        parser.error("--png-size must be at least 16.")
    return args


def square_image(source: Path) -> Image.Image:
    image = Image.open(source).convert("RGBA")
    side = max(image.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    offset = ((side - image.width) // 2, (side - image.height) // 2)
    canvas.paste(image, offset, image)
    return canvas


def main() -> None:
    args = parse_args()
    image = square_image(args.source)
    resampling = Image.Resampling.LANCZOS

    if args.png is not None:
        args.png.parent.mkdir(parents=True, exist_ok=True)
        image.resize(
            (args.png_size, args.png_size),
            resampling,
        ).save(args.png, format="PNG", optimize=True)

    if args.ico is not None:
        args.ico.parent.mkdir(parents=True, exist_ok=True)
        image.save(
            args.ico,
            format="ICO",
            sizes=[(size, size) for size in ICO_SIZES],
        )


if __name__ == "__main__":
    main()
