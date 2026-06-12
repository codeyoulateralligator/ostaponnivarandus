#!/usr/bin/env python3

from PIL import Image, ImageOps

# Input images
imgs = ["ass1.png", "ass2.png"]

# A4 size in pixels at 300 DPI
A4_WIDTH, A4_HEIGHT = 2480, 3508

pages = []

for path in imgs:
    img = Image.open(path).convert("RGB")

    # Scale image to fit inside A4 while keeping aspect ratio
    img.thumbnail((A4_WIDTH, A4_HEIGHT), Image.LANCZOS)

    # Create blank white A4 page
    page = Image.new("RGB", (A4_WIDTH, A4_HEIGHT), "white")

    # Center the image
    x = (A4_WIDTH - img.width) // 2
    y = (A4_HEIGHT - img.height) // 2
    page.paste(img, (x, y))

    pages.append(page)

# Save as multi‑page PDF
pages[0].save("ass.pdf", save_all=True, append_images=pages[1:])
