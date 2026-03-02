"""
Генерация встроенных PNG-штампов для PDF-режима.
Запускается один раз или при сборке — создаёт assets/stamps/*.png.
"""

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def get_assets_dir() -> Path:
    return Path(__file__).parent / "assets" / "stamps"


def generate_daisy(path: Path, size: int = 100):
    """Генерирует простую ромашку."""
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    r_petal = size // 5
    r_center = size // 8

    import math
    # Лепестки
    for i in range(8):
        angle = i * (360 / 8)
        rad = math.radians(angle)
        px = cx + int((size // 3) * math.cos(rad))
        py = cy + int((size // 3) * math.sin(rad))
        draw.ellipse(
            [px - r_petal, py - r_petal, px + r_petal, py + r_petal],
            fill=(255, 255, 255, 255),
            outline=(100, 180, 100, 255),
            width=2,
        )
    # Центр
    draw.ellipse(
        [cx - r_center, cy - r_center, cx + r_center, cy + r_center],
        fill=(255, 220, 50, 255),
        outline=(200, 180, 30, 255),
        width=2,
    )
    img.save(str(path), "PNG")


def generate_lock(path: Path, size: int = 100):
    """Генерирует иконку замка."""
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Тело замка
    body_x1, body_y1 = size // 4, size // 2
    body_x2, body_y2 = 3 * size // 4, 5 * size // 6
    draw.rectangle([body_x1, body_y1, body_x2, body_y2],
                    fill=(80, 80, 80, 255), outline=(50, 50, 50, 255), width=2)

    # Дужка
    arc_x1, arc_y1 = size // 3, size // 6
    arc_x2, arc_y2 = 2 * size // 3, size // 2 + size // 10
    draw.arc([arc_x1, arc_y1, arc_x2, arc_y2], 0, 360,
             fill=(60, 60, 60, 255), width=4)

    # Замочная скважина
    kx, ky = size // 2, 2 * size // 3
    kr = size // 14
    draw.ellipse([kx - kr, ky - kr, kx + kr, ky + kr],
                  fill=(200, 200, 200, 255))

    img.save(str(path), "PNG")


def generate_confidential(path: Path, width: int = 200, height: int = 40):
    """Генерирует плашку «КОНФИДЕНЦИАЛЬНО»."""
    img = Image.new("RGBA", (width, height), (220, 30, 30, 255))
    draw = ImageDraw.Draw(img)

    # Рамка
    draw.rectangle([1, 1, width - 2, height - 2],
                    outline=(255, 255, 255, 200), width=2)

    # Текст
    text = "КОНФИДЕНЦИАЛЬНО"
    font = ImageFont.load_default()
    # Try system fonts that support Cyrillic
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
        "C:/Windows/Fonts/arial.ttf",  # Windows
        "C:/Windows/Fonts/arialbd.ttf",  # Windows bold
        "/System/Library/Fonts/Helvetica.ttc",  # macOS
    ]
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, 14)
            break
        except (OSError, IOError):
            continue

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (width - tw) // 2
    ty = (height - th) // 2
    draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

    img.save(str(path), "PNG")


def generate_star(path: Path, size: int = 100):
    """Генерирует звёздочку."""
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    import math
    cx, cy = size // 2, size // 2
    outer_r = size // 2 - 5
    inner_r = outer_r // 2.5
    points = []
    for i in range(10):
        angle = math.radians(i * 36 - 90)
        r = outer_r if i % 2 == 0 else inner_r
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

    draw.polygon(points, fill=(255, 200, 0, 255), outline=(200, 150, 0, 255), width=2)
    img.save(str(path), "PNG")


def main():
    stamps_dir = get_assets_dir()
    stamps_dir.mkdir(parents=True, exist_ok=True)

    print("Generating stamps...")
    generate_daisy(stamps_dir / "daisy.png")
    print("  + daisy.png")
    generate_lock(stamps_dir / "lock.png")
    print("  + lock.png")
    generate_confidential(stamps_dir / "confidential.png")
    print("  + confidential.png")
    generate_star(stamps_dir / "star.png")
    print("  + star.png")
    print("Done!")


if __name__ == "__main__":
    main()
