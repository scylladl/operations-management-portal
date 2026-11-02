"""
Slideshow GIF from screenshots, for the README: each frame resized to WIDTH, shown for SECONDS, looping.

    python scripts/make_tour_gif.py OUT WIDTH SECONDS FRAME [FRAME ...]

Needs Pillow (installed with Streamlit). 128 colours without dithering keeps flat UI colours clean and the file small.
"""
import sys

from PIL import Image

out, width, seconds, frames = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4:]
images = []
for path in frames:
    image = Image.open(path).convert("RGB")
    image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    images.append(image.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
images[0].save(out, save_all=True, append_images=images[1:], duration=int(seconds * 1000), loop=0, optimize=True)
print(out, images[0].size, len(images), "frames")
