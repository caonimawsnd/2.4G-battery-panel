"""把白底产品图做成透明底 PNG，供设备卡片使用。

白底图的边缘很干净（3px 内从物体过渡到纯白），用 floodfill 从四角灌一遍
就能拿到背景区域；过渡带按「接近纯白的程度」给一个软 alpha，避免出现白边。
透明底的好处：普通卡片上背景由 .imgbox 提供（#F1F3F5，观感和现在一致），
开启毛玻璃后鼠标能直接浮在玻璃上。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(r"C:\Users\QQ339\.workbuddy-ai\clipboard-images\clipboard-2026-10-30T03-53-43-930Z-253c1838.jpg")
DST = ROOT / "ui" / "img" / "rapoo.png"

CANVAS = (660, 300)
BODY_H = 268
MARK = (255, 0, 255)


def main():
    im = Image.open(SRC).convert("RGB")
    a = np.asarray(im).astype(np.float32)

    # 1) 去水印：右下角非白像素填白
    h, w, _ = a.shape
    y0, x0 = int(h * 0.94), int(w * 0.75)
    ys, xs = np.nonzero(a[y0:, x0:].min(axis=2) < 250)
    if ys.size:
        a[y0 + ys.min() - 4:y0 + ys.max() + 5,
          x0 + xs.min() - 4:x0 + xs.max() + 5] = 255.0
        print("watermark removed")

    im = Image.fromarray(a.astype(np.uint8), "RGB")

    # 2) 从四角灌色，标出背景区域
    for seed in [(0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1)]:
        ImageDraw.floodfill(im, seed, MARK, thresh=18)
    arr = np.asarray(im).astype(np.int16)
    bg = (arr[..., 0] == MARK[0]) & (arr[..., 1] == MARK[1]) & (arr[..., 2] == MARK[2])

    # 3) 还原成真实颜色
    rgb = a.copy()

    # 4) alpha：背景透明，边界按「接近纯白的程度」软过渡
    mn = rgb.min(axis=2)
    near_white = np.clip((mn - 234.0) / 21.0, 0, 1)
    bg_d = np.asarray(Image.fromarray((bg * 255).astype(np.uint8))
                      .filter(ImageFilter.MaxFilter(5))) > 127
    alpha = np.where(bg, 0.0, np.where(bg_d, 1.0 - near_white, 1.0))
    alpha = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8))
                       .filter(ImageFilter.GaussianBlur(0.6)), dtype=np.float32) / 255.0
    alpha[bg & (alpha < 0.06)] = 0.0

    out = np.concatenate([rgb, (alpha * 255)[..., None]], axis=2)
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")

    # 5) 裁到内容区并缩放
    bbox = img.split()[-1].getbbox()
    print("bbox", bbox)
    body = img.crop(bbox)
    scale = BODY_H / body.height
    body = body.resize((round(body.width * scale), BODY_H), Image.LANCZOS)

    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    canvas.alpha_composite(body, ((CANVAS[0] - body.width) // 2,
                                  (CANVAS[1] - body.height) // 2))
    canvas.save(DST)
    print("saved", DST, canvas.size, "mouse", body.size)


if __name__ == "__main__":
    sys.exit(main())
