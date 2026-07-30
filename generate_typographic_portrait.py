from __future__ import annotations

from pathlib import Path
import random

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


ROOT = Path("/Users/musammataktar/Documents/Github")
TEMPLATE = Path(
    "/Users/musammataktar/.codex/generated_images/019fa6d7-fccd-7e81-9e77-4e3bcffcb9a2/"
    "call_g1VB8wM7AxxdAiZQHi6Fbjaj.png"
)
OUTPUTS = [
    ROOT / "typographic-portrait-hero.png",
    ROOT / "assets/profile/typographic-portrait-hero.png",
]
GIF_OUTPUTS = [
    ROOT / "typographic-portrait-typing.gif",
    ROOT / "assets/profile/typographic-portrait-typing.gif",
]
FONT_PATH = Path("/System/Library/Fonts/SFNSMono.ttf")


def add_background(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    draw.rectangle((0, 0, width, height), fill="white")
    for x in range(0, width, 5):
        shade = 236 if (x // 5) % 2 == 0 else 244
        draw.line((x, 0, x, height), fill=(shade, shade, shade), width=1)


def draw_cursor(
    frame: Image.Image,
    x: int,
    y: int,
    cell_w: int,
    cell_h: int,
) -> None:
    cursor = ImageDraw.Draw(frame)
    bar_w = max(3, cell_w // 5)
    x0 = max(0, min(frame.size[0] - 1, x))
    y0 = max(0, min(frame.size[1] - 1, y))
    x1 = max(x0, min(frame.size[0] - 1, x0 + bar_w))
    y1 = max(y0, min(frame.size[1] - 1, y0 + cell_h - 2))
    cursor.rectangle((x0, y0, x1, y1), fill="black")
    cursor.rectangle((x0, y0, min(frame.size[0] - 1, x0 + 1), y1), fill="white")


def as_gif_frame(frame: Image.Image) -> Image.Image:
    return frame.quantize(colors=16, method=Image.Quantize.MEDIANCUT)


def render() -> None:
    random.seed(7)

    template = Image.open(TEMPLATE).convert("L")
    target_size = template.size
    tone = ImageEnhance.Contrast(template).enhance(1.2).filter(ImageFilter.GaussianBlur(5.5))
    detail = tone.filter(ImageFilter.FIND_EDGES)
    detail = ImageEnhance.Contrast(detail).enhance(2.0)
    template_arr = np.asarray(template, dtype=np.uint8)
    tone_arr = np.asarray(tone, dtype=np.uint8)
    detail_arr = np.asarray(detail, dtype=np.uint8)
    presence = Image.fromarray(255 - template_arr, mode="L").filter(ImageFilter.GaussianBlur(10))
    presence_arr = np.asarray(presence, dtype=np.uint8)

    out = Image.new("RGB", target_size, "white")
    draw = ImageDraw.Draw(out)
    add_background(draw, *target_size)

    font_size = 28
    font = ImageFont.truetype(str(FONT_PATH), font_size)
    sample_box = draw.textbbox((0, 0), "@", font=font)
    cell_w = sample_box[2] - sample_box[0]
    cell_h = sample_box[3] - sample_box[1] + 5

    dark_chars = "@80B#XQWM"
    mid_chars = "O0&%8XZ+="
    light_chars = "I!;:.,"
    solid_black = 72
    subject_ink = 18
    subject_presence = 14

    black_mask = Image.fromarray((template_arr < solid_black).astype(np.uint8) * 255, mode="L")
    out.paste("black", (0, 0), black_mask)

    width, height = target_size
    for top in range(0, height, cell_h):
        for left in range(0, width, cell_w):
            box = (
                left,
                top,
                min(left + cell_w, width),
                min(top + cell_h, height),
            )
            template_region = template_arr[box[1] : box[3], box[0] : box[2]]
            tone_region = tone_arr[box[1] : box[3], box[0] : box[2]]
            detail_region = detail_arr[box[1] : box[3], box[0] : box[2]]
            presence_region = presence_arr[box[1] : box[3], box[0] : box[2]]

            black_ratio = float((template_region < solid_black).mean())
            subject_ratio = float((template_region < 210).mean())
            mean = float(tone_region.mean())
            edge = float(detail_region.mean())
            presence_mean = float(presence_region.mean())

            if black_ratio > 0.42:
                continue

            if presence_mean < subject_presence:
                continue

            if subject_ratio < subject_ink / 100:
                continue

            if edge > 68 or mean < 118:
                pool = dark_chars
            elif edge > 38 or mean < 164:
                pool = mid_chars
            else:
                pool = light_chars

            char = random.choice(pool)
            baseline_y = top - 2
            draw.text((left, baseline_y), char, font=font, fill="black")

    for output in OUTPUTS:
        output.parent.mkdir(parents=True, exist_ok=True)
        out.save(output)

    gif_width = 900
    gif_height = round(height * gif_width / width)
    final_small = out.resize((gif_width, gif_height), Image.Resampling.NEAREST)

    bg_small = Image.new("RGB", final_small.size, "white")
    bg_draw = ImageDraw.Draw(bg_small)
    add_background(bg_draw, *final_small.size)

    scaled_cell_w = max(10, round(cell_w * gif_width / width))
    scaled_cell_h = max(16, round(cell_h * gif_height / height))
    cols = (gif_width + scaled_cell_w - 1) // scaled_cell_w
    rows = (gif_height + scaled_cell_h - 1) // scaled_cell_h

    frames: list[Image.Image] = []
    durations: list[int] = []
    step_pattern = [7, 8, 6, 9, 7, 8]
    pattern_idx = 0

    start_frame = bg_small.copy()
    draw_cursor(start_frame, 0, 0, scaled_cell_w, scaled_cell_h)
    frames.append(as_gif_frame(start_frame))
    durations.append(180)

    def build_frame(row: int, revealed_cols: int) -> Image.Image:
        frame = bg_small.copy()
        if row > 0:
            revealed_h = min(gif_height, row * scaled_cell_h)
            region = final_small.crop((0, 0, gif_width, revealed_h))
            frame.paste(region, (0, 0))
        if revealed_cols > 0 and row < rows:
            top = row * scaled_cell_h
            bottom = min(gif_height, top + scaled_cell_h)
            revealed_w = min(gif_width, revealed_cols * scaled_cell_w)
            region = final_small.crop((0, top, revealed_w, bottom))
            frame.paste(region, (0, top))
        return frame

    for row in range(rows):
        revealed_cols = 0
        while revealed_cols < cols:
            step = min(step_pattern[pattern_idx % len(step_pattern)], cols - revealed_cols)
            pattern_idx += 1
            revealed_cols += step

            frame = build_frame(row, revealed_cols)
            if row < rows - 1 or revealed_cols < cols:
                cursor_col = min(cols - 1, revealed_cols)
                cursor_x = min(gif_width - 1, cursor_col * scaled_cell_w)
                cursor_y = row * scaled_cell_h
                draw_cursor(frame, cursor_x, cursor_y, scaled_cell_w, scaled_cell_h)

            frames.append(as_gif_frame(frame))
            durations.append(42 if revealed_cols < cols else 120)

        if row < rows - 1:
            next_line_frame = build_frame(row + 1, 0)
            draw_cursor(next_line_frame, 0, (row + 1) * scaled_cell_h, scaled_cell_w, scaled_cell_h)
            frames.append(as_gif_frame(next_line_frame))
            durations.append(120)

    frames.append(as_gif_frame(final_small))
    durations.append(2600)

    for output in GIF_OUTPUTS:
        output.parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(
            output,
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            disposal=2,
            optimize=True,
        )


if __name__ == "__main__":
    render()
