#!/usr/bin/env python3
"""Flash AI News avatar (2026-10-06): black disc, thin neon-green ring, green
lightning bolt. Drawn in code (no AI image). Writes avatar-flash.png (512px,
reel tweet-frame) and avatar-flash-1080.png (IG profile photo upload)."""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
BLACK, GREEN = (5, 7, 6), (0, 230, 118)
BOLT = [(14.2, 1), (4, 13.6), (10.4, 13.6), (8.9, 23), (20, 9.6), (13.6, 9.6)]  # 24x24 box


def avatar(size):
    s = size * 4  # supersample, then downscale for smooth edges
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, s - 1, s - 1), fill=BLACK)
    ring = round(s * 0.035)
    m = round(s * 0.06)
    d.ellipse((m, m, s - 1 - m, s - 1 - m), outline=GREEN, width=ring)
    k, off = s * 0.56 / 24, s * 0.22  # bolt fills the middle ~56%
    d.polygon([(off + x * k, off + y * k) for x, y in BOLT], fill=GREEN)
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    avatar(512).save(os.path.join(HERE, "avatar-flash.png"))
    avatar(1080).save(os.path.join(HERE, "avatar-flash-1080.png"))
