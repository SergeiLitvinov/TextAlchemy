"""Own printed text on a blank raster for native OCR consumer acceptance."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LINES = ('Пример 123', 'Документ 456', 'Report 789')


def write_printed_page(path: Path, font_path: Path) -> Path:
    image = Image.new('RGB', (1000, 360), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 48)
    for index, text in enumerate(LINES):
        draw.text((60, 40 + 100 * index), text, font=font, fill='black')
    image.save(path)
    return path
