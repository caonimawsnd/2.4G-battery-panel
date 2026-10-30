"""从驱动截图里抠出 VT3S 鼠标，输出带 alpha 的产品图。

背景是近乎纯色的深灰蓝 (28,29,34)，鼠标本体反而更暗，
所以用"与背景色的距离"做遮罩，再取最大连通域 + 填洞 + 羽化。
"""
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SHOT = Path(r"C:\Users\QQ339\.workbuddy-ai\clipboard-images\clipboard-2026-10-30T03-24-44-539Z-c61bafe8.jpg")

# 截图里鼠标所在区域（留足边距）
CROP = (330, 225, 565, 645)
BG = np.array([28.0, 29.0, 34.0])

T_LO = 3.5    # 低于此距离视为纯背景
T_HI = 13.0   # 高于此距离视为纯前景


def fblur(a, sigma):
    """可分离盒式模糊近似高斯（float 精度）"""
    def box(arr, r, axis):
        if r < 1:
            return arr
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r + 1, r)
        p = np.pad(arr, pad, mode="edge")
        cs = np.cumsum(p, axis=axis)
        n = arr.shape[axis]
        hi = [slice(None), slice(None)]
        lo = [slice(None), slice(None)]
        hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
        lo[axis] = slice(0, n)
        return (cs[tuple(hi)] - cs[tuple(lo)]) / (2 * r + 1)

    r = max(1, int(round((np.sqrt(4.0 * sigma * sigma + 1.0) - 1.0) / 2.0)))
    out = a.astype(np.float32)
    for _ in range(3):
        out = box(out, r, 0)
        out = box(out, r, 1)
    return out


def largest_component(mask):
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best = np.zeros_like(mask, dtype=bool)
    best_n = 0
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or seen[sy, sx]:
                continue
            q = deque([(sy, sx)])
            seen[sy, sx] = True
            comp = []
            while q:
                y, x = q.popleft()
                comp.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((ny, nx))
            if len(comp) > best_n:
                best_n = len(comp)
                best = np.zeros_like(mask, dtype=bool)
                for y, x in comp:
                    best[y, x] = True
    return best


def fill_holes(mask):
    h, w = mask.shape
    outside = np.zeros_like(mask, dtype=bool)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not mask[y, x] and not outside[y, x]:
                outside[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if not mask[y, x] and not outside[y, x]:
                outside[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not mask[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                q.append((ny, nx))
    return mask | (~outside & ~mask)


SS = 4          # 超采样倍数：轮廓平滑和抗锯齿都在 4x 上做
FLOW_SIGMA = 8.0
FLOW_ITERS = 4


def curvature_smooth(field, sigma, iters, thr=0.5):
    """模糊+二值化反复迭代 ≈ 曲率流：抹掉小尺度锯齿，保住大形。"""
    f = field
    for _ in range(iters):
        f = np.where(fblur(f, sigma) > thr, 1.0, 0.0)
    return f


def main():
    im = Image.open(SHOT).convert("RGB").crop(CROP)
    a = np.asarray(im).astype(np.float32)

    dist = np.sqrt(((a - BG) ** 2).sum(axis=2))
    soft = np.clip((dist - T_LO) / (T_HI - T_LO), 0, 1)

    # 1) 1x 上先定连通域（去掉零星噪点、填掉内部空洞）
    solid = dist > 6.0
    solid = largest_component(solid)
    solid = fill_holes(solid)

    # 2) 放大到 4x 再处理，才有足够分辨率把轮廓磨平
    #    注意输入必须是「填好洞的二值轮廓」：用色差软场会把鼠标内部
    #    与背景同色的区域当成外部，平滑后炸出一堆洞。
    w, h = im.size
    solid_img = Image.fromarray((solid * 255).astype(np.uint8))
    big_solid = np.asarray(solid_img.resize((w * SS, h * SS), Image.BICUBIC),
                           dtype=np.float32) / 255.0

    # 3) 曲率流：把 JPEG 啃出来的锯齿一点点化开
    field = curvature_smooth(big_solid, FLOW_SIGMA, FLOW_ITERS)

    # 4) 边缘做成等宽的抗锯齿过渡
    alpha = fblur(field, 0.9)
    alpha = np.clip((alpha - 0.5) / 0.18 + 0.5, 0, 1)
    alpha = alpha * alpha * (3 - 2 * alpha)

    # 6) 背景是深色，边缘不做反解（反解会把紫色轮廓光提成白边）
    big_rgb = np.asarray(im.resize((w * SS, h * SS), Image.BICUBIC),
                         dtype=np.float32)

    out = np.concatenate([big_rgb, (alpha * 255)[..., None]], axis=2)
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")

    bbox = img.split()[-1].getbbox()
    pad = 2 * SS
    ox, oy = bbox[0] - pad, bbox[1] - pad
    img = img.crop((max(0, ox), max(0, oy),
                    min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad)))
    img.save(ROOT / "tools" / "_cutout.png")
    print("cutout", img.size)

    # 诊断图：把最终轮廓画在原始截图上，绿色=轮廓线
    a_cut = np.asarray(img)[..., 3].astype(np.float32) / 255.0
    edge = np.zeros_like(a_cut)
    edge[1:-1, 1:-1] = np.abs(
        a_cut[1:-1, 1:-1] - a_cut[2:, 1:-1]) + np.abs(
        a_cut[1:-1, 1:-1] - a_cut[1:-1, 2:])
    edge = edge > 0.25
    over = big_rgb[oy:oy + img.height, ox:ox + img.width].copy()
    over[edge] = [0, 255, 60]
    Image.fromarray(over.astype(np.uint8)).save(ROOT / "tools" / "_overlay.png")

    # 放到三种底色上检查
    for name, col in [("white", (255, 255, 255)), ("light", (238, 241, 245)),
                      ("dark", (28, 30, 36))]:
        bg = Image.new("RGBA", img.size, col + (255,))
        bg.alpha_composite(img)
        bg.convert("RGB").save(ROOT / "tools" / f"_cut_{name}.png")


if __name__ == "__main__":
    sys.exit(main())
