#!/usr/bin/env python3
"""
Generates a sample high-res (512x512) RGBA PNG icon in assets/icons/hello.png
to test the automated build.rs baking pipeline.
"""
import os
import math
from PIL import Image, ImageDraw

def create_sample_icon(path):
    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw rounded squircle background with vertical gradient
    # iOS squircle corner radius ~ 22.5% of size
    radius = int(size * 0.225)
    
    # Gradient from vibrant coral/orange to magenta/purple
    # (255, 107, 107) -> (142, 68, 173)
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    base_draw = ImageDraw.Draw(base)
    base_draw.rounded_rectangle([16, 16, size - 17, size - 17], radius=radius, fill=(255, 255, 255, 255))
    
    for y in range(size):
        t = y / float(size)
        r = int(255 * (1 - t) + 142 * t)
        g = int(107 * (1 - t) + 68 * t)
        b = int(107 * (1 - t) + 173 * t)
        for x in range(size):
            alpha = base.getpixel((x, y))[3]
            if alpha > 0:
                img.putpixel((x, y), (r, g, b, alpha))

    # Draw a cute glowing star/sparkle in the center
    center = size // 2
    draw = ImageDraw.Draw(img)
    # Circle in center
    draw.ellipse([center - 70, center - 70, center + 70, center + 70], fill=(255, 255, 255, 230))
    # Horizontal bar
    draw.rounded_rectangle([center - 130, center - 35, center + 130, center + 35], radius=35, fill=(255, 255, 255, 230))
    # Vertical bar
    draw.rounded_rectangle([center - 35, center - 130, center + 35, center + 130], radius=35, fill=(255, 255, 255, 230))

    img.save(path, "PNG")
    print(f"Sample icon generated at {path}")

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")
    os.makedirs(out_dir, exist_ok=True)
    create_sample_icon(os.path.join(out_dir, "hello.png"))
