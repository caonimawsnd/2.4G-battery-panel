"""把黑壳产品图转换成"白模"(clay render) 风格。

思路：
1. 取原图 alpha 作轮廓，先放大 4 倍再处理，避免锯齿。
2. 用轮廓模糊生成"穹顶"高度场，求法线做方向光，补上黑壳图缺失的曲面体积。
3. 叠加原图亮度细节（缝隙/滚轮/logo），保住结构可读性。
4. 边缘 AO 压暗侧壁，最后整体映射到浅灰白区间，去掉黑壳材质。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ui" / "img" / "rapoo.png"
OUT_SAME = ROOT / "ui" / "img" / "rapoo_clay.png"
OUT_BIG = ROOT / "tools" / "_clay_big.png"
OUT_WHITE = ROOT / "tools" / "_clay_white.png"

SCALE = 4

DEFAULTS = dict(body=0.655, span=0.345, dome_mix=0.40, ao_s=0.38,
                spec_amt=0.06, k_scale=0.028, detail_blur=2.0)


def to_arr(im):
    return np.asarray(im, dtype=np.float32) / 255.0


def to_img(a):
    return Image.fromarray(np.clip(a * 255.0, 0, 255).astype(np.uint8))


def _box(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    if r < 1:
        return a
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    p = np.pad(a, pad, mode="edge")
    cs = np.cumsum(p, axis=axis)
    n = a.shape[axis]
    hi = [slice(None), slice(None)]
    lo = [slice(None), slice(None)]
    hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
    lo[axis] = slice(0, n)
    return (cs[tuple(hi)] - cs[tuple(lo)]) / (2 * r + 1)


def fblur(a: np.ndarray, sigma: float) -> np.ndarray:
    """float 精度高斯模糊（三次盒式近似），避免 8 位量化产生色阶环带"""
    if sigma <= 0.3:
        return a.astype(np.float32)
    r = max(1, int(round((np.sqrt(4.0 * sigma * sigma + 1.0) - 1.0) / 2.0)))
    out = a.astype(np.float32)
    for _ in range(3):
        out = _box(out, r, 0)
        out = _box(out, r, 1)
    return out


def norm01(a, mask, lo=2.0, hi=98.0):
    vals = a[mask > 0.5]
    if vals.size == 0:
        return a
    p_lo, p_hi = np.percentile(vals, [lo, hi])
    if p_hi - p_lo < 1e-4:
        return np.zeros_like(a)
    return np.clip((a - p_lo) / (p_hi - p_lo), 0, 1)


def smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def clay(src: Image.Image, **kw):
    p = dict(DEFAULTS)
    p.update(kw)
    w, h = src.size
    big = src.resize((w * SCALE, h * SCALE), Image.LANCZOS)
    arr = to_arr(big)
    rgb, alpha = arr[..., :3], arr[..., 3]
    solid = (alpha > 0.5).astype(np.float32)
    L = max(w, h) * SCALE / 2.0

    # 1) 原图亮度细节（缝隙、滚轮、logo）
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    detail = norm01(fblur(lum, p["detail_blur"]), alpha, 1.0, 99.0)

    # 2) 轮廓 -> 高度场 -> 法线
    dome = norm01(fblur(solid, 0.20 * L), alpha, 0.0, 99.8)
    height = smoothstep(dome) ** 0.75
    gy, gx = np.gradient(height)
    nx, ny, nz = -gx * p["k_scale"] * L, -gy * p["k_scale"] * L, np.ones_like(height)
    nlen = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
    nx, ny, nz = nx / nlen, ny / nlen, nz / nlen

    def lam(lx, ly, lz, wrap=0.5):
        ln = np.sqrt(lx * lx + ly * ly + lz * lz)
        return np.clip(((nx * lx + ny * ly + nz * lz) / ln + wrap) / (1 + wrap), 0, 1)

    key = lam(-0.50, -0.58, 0.80)   # 左上前方主光
    fill = lam(0.55, 0.10, 0.72)    # 右侧补光

    hv = 0.5 * np.array([-0.50, -0.58, 0.80]) + np.array([0, 0, 1.0])
    hv = hv / np.linalg.norm(hv)
    spec = np.clip(nx * hv[0] + ny * hv[1] + nz * hv[2], 0, 1) ** 28

    # 3) 边缘 AO：侧壁转下去处压暗
    ao = norm01(fblur(solid, 0.038 * L), alpha, 0.0, 99.0)
    ao = (1.0 - p["ao_s"]) + p["ao_s"] * smoothstep(ao)

    base = p["dome_mix"] * dome ** 1.1 + (1 - p["dome_mix"]) * detail
    shade = (0.55 * base + 0.45 * (0.35 * key + 0.35 * fill + 0.30)) * ao
    shade = np.clip(shade + p["spec_amt"] * spec, 0, 1)

    v = p["body"] + p["span"] * shade
    out = np.stack([v * 0.982, v * 0.990, v], axis=-1)  # 极轻冷调
    out = np.concatenate([out, alpha[..., None]], axis=-1)
    return to_img(out)


def main():
    src = Image.open(SRC).convert("RGBA")
    big = clay(src)

    bbox = big.split()[-1].getbbox()
    pad = 24
    crop = big.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                     min(big.width, bbox[2] + pad), min(big.height, bbox[3] + pad)))
    crop.save(OUT_BIG)

    # 与原图同尺寸/同位置，可直接替换 rapoo.png
    same = crop.resize((round(crop.width / SCALE), round(crop.height / SCALE)),
                       Image.LANCZOS)
    canvas = Image.new("RGBA", src.size, (0, 0, 0, 0))
    canvas.alpha_composite(same, (max(0, bbox[0] // SCALE - pad // SCALE),
                                  max(0, bbox[1] // SCALE - pad // SCALE)))
    canvas.save(OUT_SAME)

    # 白底版：加柔和接触阴影
    white = Image.new("RGBA", crop.size, (255, 255, 255, 255))
    a = crop.split()[-1].point(lambda v: int(v * 0.13))
    shadow = Image.new("RGBA", crop.size, (86, 92, 106, 255))
    shadow.putalpha(a.filter(ImageFilter.GaussianBlur(crop.width * 0.05)))
    shadow = shadow.transform(crop.size, Image.AFFINE, (1, 0, 0, 0, 1, -8),
                              resample=Image.BICUBIC)
    white = Image.alpha_composite(white, shadow)
    white = Image.alpha_composite(white, crop)
    white.convert("RGB").save(OUT_WHITE)

    print("big  ", OUT_BIG, crop.size)
    print("same", OUT_SAME, canvas.size)
    print("white", OUT_WHITE)


if __name__ == "__main__":
    sys.exit(main())
