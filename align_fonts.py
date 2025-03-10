"""
Script to calculate offsets for the characters of a font in order to align them (pixel-wise) to another font.
"""

import json, base64
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import cv2


DEFAULT_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
OUTPUT_FOLDER = "out"


def run(overlay_font_path, base_font_path):
    Path(OUTPUT_FOLDER).mkdir(exist_ok=True)

    print("Optimizing", Path(overlay_font_path).stem, "on", Path(base_font_path).stem, "...", flush=True)
    result = align_font(overlay_font_path, base_font_path)
    print("Writing json...", flush=True)
    write_json(result)

    print("Writing report...", flush=True)
    write_report(result)


def align_font(overlay_font_path, base_font_path, font_size=128, score_epsilon=1e-5, scale_epsilon=0.01, resolution=25) -> dict:
    base_font = ImageFont.truetype(base_font_path, font_size)
    low_scale, high_scale = 0.5, 2.0
    while True:
        scales = np.linspace(low_scale, high_scale, resolution)
        results = [align_font_instance(ImageFont.truetype(overlay_font_path, scale * font_size), base_font)
                   for scale in scales]
        min_i = np.argmin([r["average_remainder"] for r in results])
        assert 0 < min_i < len(results) - 1, "Initial bounds are too narrow."
        low_scale, high_scale = scales[min_i - 1], scales[min_i + 1]

        if (
            (abs(results[min_i - 1]["average_remainder"] - results[min_i]["average_remainder"]) < score_epsilon and
             abs(results[min_i + 1]["average_remainder"] - results[min_i]["average_remainder"]) < score_epsilon) or
            high_scale - low_scale < scale_epsilon
        ):
            return {
                "base_font": Path(base_font_path).stem,
                "base_font_path": base_font_path,
                "overlay_font": Path(overlay_font_path).stem,
                "overlay_font_path": overlay_font_path,
                "font_scale": scales[min_i],
                **results[min_i]
            }


def align_font_instance(overlay_font: ImageFont.FreeTypeFont, base_font: ImageFont.FreeTypeFont, charset=DEFAULT_CHARS) -> dict:
    """
    Takes two font objects and returns a dictionary with optimal offsets, individual scores, and a total score.
    """
    optimization_result = {"average_remainder": None, "offsets": {}}
    for char in charset:
        optimization_result["offsets"][char] = optimize_offset(char, overlay_font, base_font)
    optimization_result["average_remainder"] = np.mean([v[1] for v in optimization_result["offsets"].values()])
    return optimization_result


def optimize_offset(char, overlay_font, ref_font):
    """
    Gradient-descents the character offset by one pixel (incl. diagonals) until a local minimum remainder is reached.
    The remainder is the number of pixels of the underlaying character not covered by the overlaying character.
    Returns offset and ratio of remainder pixels.
    """
    # Start with both characters centered horizontally
    ref_img, x1 = char_to_image_array(char, ref_font)
    overlay_img, x2 = char_to_image_array(char, overlay_font, (ref_img.shape[1], ref_img.shape[0]))
    ref_img /= 255.0
    overlay_img /= 255.0
    offset = (0, 0)
    remainders = {offset: np.sum(overlay_img * (1.0 - ref_img))}
    neighbors = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]

    while True:
        neighbor_remainders = []
        for dx, dy in neighbors:
            new_offset = (offset[0] + dx, offset[1] + dy)
            if new_offset not in remainders:
                img = move_image(overlay_img, *new_offset)
                remainder = np.sum(img * (1.0 - ref_img))
                remainders[new_offset] = remainder
            neighbor_remainders.append(remainders[new_offset])
        i = np.argmin(neighbor_remainders)
        if neighbor_remainders[i] >= remainders[offset]:
            break
        offset = tuple(np.asarray(offset) + neighbors[i])

    score = remainders[offset] / (ref_img.shape[0] * ref_img.shape[1])  # total pixels to ratio
    offset = (offset[0] - x1 + x2, offset[1])  # add initial offset from horizontal centering
    offset = tuple(np.asarray(offset) / overlay_font.size)
    return offset, score


def move_image(img, dx, dy, pad_color=255):
    if dx > 0:
        img = np.pad(img, ((0, 0), (dx, 0)), mode="constant", constant_values=pad_color)[:, :-dx]
    if dx < 0:
        img = np.pad(img, ((0, 0), (0, -dx)), mode="constant", constant_values=pad_color)[:, -dx:]
    if dy > 0:
        img = np.pad(img, ((dy, 0), (0, 0)), mode="constant", constant_values=pad_color)[:-dy, :]
    if dy < 0:
        img = np.pad(img, ((0, -dy), (0, 0)), mode="constant", constant_values=pad_color)[-dy:, :]
    return img


def char_to_image_array(char, font, image_size=None, x=None):
    # Create a blank image with white background
    if image_size is None:
        image_size = (int(1.333 * font.size), int(1.333 * font.size))
    image = Image.new("L", image_size, 255)
    draw = ImageDraw.Draw(image)

    # Determine x position
    if x is None:
        bb = draw.textbbox((0, 0), char, font=font)
        w = bb[2] - bb[0] + 1
        x = int((image_size[0] - w) / 2)

    # Render the text
    draw.text((x, 0.75 * image_size[0]), char, font=font, anchor="ls", fill=0)

    # Convert image to NumPy array
    image_array = np.array(image, float)

    return image_array, x


def write_json(align_font_result):
    filename = f"{align_font_result['overlay_font']}_on_{align_font_result['base_font']}.json"
    with open(f"{OUTPUT_FOLDER}/{filename}", "w") as f:
        json.dump(align_font_result, f, indent=2)


def write_report(align_font_result, charset=DEFAULT_CHARS, font_size=128):
    filename = f"{align_font_result['overlay_font']}_on_{align_font_result['base_font']}.html"
    base_font = ImageFont.truetype(align_font_result["base_font_path"], font_size)
    overlay_font = ImageFont.truetype(align_font_result["overlay_font_path"], align_font_result['font_scale'] * font_size)

    with open(f"{OUTPUT_FOLDER}/{filename}", "w") as f:
        f.write("<html><head><style>"
                "table, th, td {"
                "  border-collapse: collapse;"
                "  border: 1px solid #ccc;"
                "}"
                "th, td {"
                "  padding: 5px;"
                "  text-align: center;"
                "}"
                "</style></head><body>")
        f.write(f"<h1>{align_font_result['overlay_font']} on {align_font_result['base_font']}</h1>")
        f.write(f"<h2>Font scale: {align_font_result['font_scale']}</h2>")
        f.write(f"<h2>Average remainder: {align_font_result['average_remainder'] * 100:.5f}%</h2>")
        f.write("<table>")
        f.write("<tr><th>Char</th><th>Offset</th><th>Remainder</th><th>Image</th></tr>")

        for char in charset:
            offset, remainder = align_font_result['offsets'][char]
            f.write(f"<tr><td>{char}</td><td>({offset[0]:.3f}, {offset[1]:.3f})</td><td>{remainder * 100:.5f}%</td>")
            img = draw_char_overlay(char, overlay_font, base_font, offset)
            img_base64 = base64.b64encode(cv2.imencode(".png", img)[1]).decode("utf-8")
            f.write(f"<td><img src='data:image/png;base64,{img_base64}'></td></tr>")

        f.write("</table>")
        f.write("</body></html>")


def draw_char_overlay(char: str, overlay_font, base_font, offset):
    offset = (int(offset[0] * overlay_font.size), int(offset[1] * overlay_font.size))
    img1, x = char_to_image_array(char, base_font)
    img2, _ = char_to_image_array(char, overlay_font, (img1.shape[1], img1.shape[0]), x)
    r = 255.0 - img1
    g = 255.0 - move_image(img2, *offset)
    b = np.zeros_like(r)
    overlap = np.minimum(g, r) > 0
    b[overlap] = 0.5 * (r[overlap] + g[overlap])
    img = np.stack([b, g, r], axis=2)
    return img


if __name__ == "__main__":
    run("fonts/Junicode-BoldItalic.ttf", "trash/fonts/AGaramond-Italic.otf")
    run("fonts/EBGaramond-Bold.ttf", "trash/fonts/AGaramond.otf")
    run("fonts/IBMPlexSans-Bold.ttf", "trash/fonts/Aptos.ttf")
    run("fonts/UnBPro-Extrabold.ttf", "trash/fonts/Arial-Bold.ttf")
    run("fonts/LiberationSans-BoldItalic.ttf", "trash/fonts/Arial-Italic.ttf")
    run("fonts/LiberationSans-Bold.ttf", "trash/fonts/Arial.ttf")
    run("fonts/ComputerModernSerif-BoldItalic.ttf", "fonts/ComputerModernSerif-Italic.ttf")
    run("fonts/ComputerModernSerif-Bold.ttf", "fonts/ComputerModernSerif.ttf")
    run("fonts/Vegur-Bold.ttf", "trash/fonts/Corbel.ttf")
    run("fonts/LinBiolinum-BoldItalic.ttf", "trash/fonts/LinBiolinum-Italic.ttf")
    run("fonts/Mignon-BoldItalic.ttf", "trash/fonts/MinionPro-Italic.ttf")
    run("fonts/Mignon-Bold.ttf", "trash/fonts/MinionPro.ttf")
    run("fonts/STIXTwoText-Bold.ttf", "trash/fonts/STIXTwoText.ttf")
    run("fonts/CrimsonText-BoldItalic.ttf", "trash/fonts/Sabon-Italic.ttf")
    run("fonts/CrimsonText-Bold.ttf", "trash/fonts/Sabon.ttf")
    run("fonts/Playfair_SemiCondensed-Bold.ttf", "trash/fonts/SuisseWorks.otf")
    run("fonts/TimesNewerRoman-BoldItalic.ttf", "trash/fonts/TimesNewRoman-Italic.ttf")
    run("fonts/TimesNewerRoman-Bold.ttf", "trash/fonts/TimesNewRoman.ttf")
    run("fonts/OpenSans_SemiCondensed-SemiBold.ttf", "trash/fonts/VectoraLH-Light.ttf")
    run("fonts/OpenSans_SemiCondensed-Bold.ttf", "trash/fonts/VectoraLH.ttf")
    run("fonts/DejaVuSans-BoldItalic.ttf", "trash/fonts/Verdana-Italic.ttf")
    run("fonts/DejaVuSans-Bold.ttf", "trash/fonts/Verdana.ttf")
