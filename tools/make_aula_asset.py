"""把白底键盘图处理成和鼠标图一致的透明底产品图。

原图 640x291 RGB，键盘几乎铺满整张画布、纯白背景 —— 放进 2.2:1 的图框里会显得
又大又满，而且白底会盖住自定义背景图。这里做两件事：

1. 从四边泛洪，把与白色连通的背景抠掉（键盘本体是银色，不会被吃掉）
2. 重新排到 660x300 的透明画布上，键盘宽度压到约 76%，和鼠标图的视觉分量对齐
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
BACKUP = ROOT / "tools" / "_aula_orig.png"   # 原始白底图（640x291）
SRC = BACKUP
OUT = ROOT / "ui" / "img" / "aula.png"

CANVAS = (660, 300)
FILL_W = 0.76          # 键盘宽度占画布比例
WHITE_THRESH = 10      # 泛洪容差：只吃掉接近纯白的像素
FEATHER = 0.8


def bg_mask(rgb: np.ndarray) -> np.ndarray:
    """从四边泛洪，返回「背景」布尔图。

    不用 PIL 的 ImageDraw.floodfill —— 它在这张图上会提前终止（只填了几百像素）。
    这里用扫描线泛洪，逐行整段填充，快且稳定。
    """
    # 用最小通道：彩色键帽（有暗通道）不会被当成白
    free = rgb.min(axis=2) >= 248
    h, w = free.shape
    seen = np.zeros((h, w), bool)
    stack: list[tuple[int, int]] = []

    for x in range(w):
        if free[0, x]:
            stack.append((0, x))
        if free[h - 1, x]:
            stack.append((h - 1, x))
    for y in range(h):
        if free[y, 0]:
            stack.append((y, 0))
        if free[y, w - 1]:
            stack.append((y, w - 1))

    while stack:
        y, x = stack.pop()
        if seen[y, x] or not free[y, x]:
            continue
        x0 = x
        while x0 > 0 and free[y, x0 - 1] and not seen[y, x0 - 1]:
            x0 -= 1
        x1 = x
        while x1 < w - 1 and free[y, x1 + 1] and not seen[y, x1 + 1]:
            x1 += 1
        seen[y, x0:x1 + 1] = True
        for ny in (y - 1, y + 1):
            if 0 <= ny < h:
                row = free[ny, x0:x1 + 1] & ~seen[ny, x0:x1 + 1]
                for i in np.nonzero(row)[0]:
                    stack.append((ny, x0 + int(i)))
    return seen


def main() -> None:
    src = Image.open(SRC).convert("RGB")
    if not BACKUP.exists():
        src.save(BACKUP)

    rgb = np.asarray(src).astype(np.float32)
    bg = bg_mask(rgb)
    fg = ~bg

    ys, xs = np.nonzero(fg)
    bbox = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    print("foreground bbox", bbox, "ratio %.1f%%" % (fg.mean() * 100))

    # alpha：内部实心，边界一像素做软化
    alpha = fg.astype(np.float32)
    a_img = Image.fromarray((alpha * 255).astype(np.uint8))
    a_img = a_img.filter(ImageFilter.GaussianBlur(FEATHER))
    alpha = np.asarray(a_img).astype(np.float32) / 255.0
    alpha[fg & (alpha < 0.55)] = 1.0     # 内部不要出现半透明麻点

    cut = np.dstack([rgb, alpha * 255.0])
    cut_img = Image.fromarray(np.clip(cut, 0, 255).astype(np.uint8), "RGBA")
    cut_img = cut_img.crop(bbox)
    print("cutout", cut_img.size)

    # 排到统一画布：按宽度占比缩放，垂直居中
    target_w = round(CANVAS[0] * FILL_W)
    target_h = round(cut_img.height * target_w / cut_img.width)
    body = cut_img.resize((target_w, target_h), Image.LANCZOS)

    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    canvas.alpha_composite(body, ((CANVAS[0] - target_w) // 2,
                                  (CANVAS[1] - target_h) // 2))
    canvas.save(OUT)

    box = canvas.split()[-1].getbbox()
    print("out", canvas.size, "bbox", box,
          "占画布 %.0f%% 宽 / %.0f%% 高" % (
              100 * (box[2] - box[0]) / CANVAS[0],
              100 * (box[3] - box[1]) / CANVAS[1]))

    # 预览：透明底、浅灰底、彩色底各一张
    for name, col in [("light", (241, 243, 245)), ("dark", (28, 33, 38)),
                      ("photo", (44, 98, 186))]:
        bgp = Image.new("RGBA", CANVAS, col + (255,))
        bgp.alpha_composite(canvas)
        bgp.convert("RGB").save(ROOT / "tools" / f"_aula_{name}.png")


if __name__ == "__main__":
    main()
