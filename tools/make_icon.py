# -*- coding: utf-8 -*-
"""tools/make_icon.py —— 生成程序图标 app.ico（纯标准库，不依赖 Pillow）

    python tools/make_icon.py

做法：把图标拆成几个有符号距离场（SDF）——圆角矩形、圆环弧——
按像素中心求距离，再用 1px 过渡做抗锯齿。这样每个尺寸都是「现算」的，
不存在把小图放大糊掉的问题，16px 下也能保持结构。

图形：一块竖置电池（含 68% 电量）+ 右侧三道 2.4G 信号弧，底色为圆角方块。
"""

import math
import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import win_icon

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

PLATE_TOP = (32, 182, 130)
PLATE_BOTTOM = (12, 106, 76)
GLYPH = (255, 255, 255)

BATTERY_LEVEL = 0.68


def _clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def sd_round_rect(px, py, cx, cy, hw, hh, r):
    """圆角矩形的有符号距离（内部为负）。"""
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def sd_arc(px, py, cx, cy, radius, width, a0, a1):
    """一段圆弧的有符号距离（角度为度，从 +x 轴起算）。"""
    dx, dy = px - cx, py - cy
    dist = math.hypot(dx, dy)
    ang = math.degrees(math.atan2(dy, dx))
    if a0 <= ang <= a1:
        return abs(dist - radius) - width / 2.0
    ends = []
    for a in (a0, a1):
        rad = math.radians(a)
        ends.append(math.hypot(px - (cx + radius * math.cos(rad)),
                               py - (cy + radius * math.sin(rad))))
    return min(ends) - width / 2.0


def _alpha(d, softness):
    """距离 -> 覆盖率，d<0 在形状内。"""
    return _clamp(0.5 - d / softness)


def _over(dst, src, a):
    """把 src 以 alpha a 覆盖到 dst（都是 0-255 三元组）。"""
    return tuple(int(round(d + (s - d) * a)) for d, s in zip(dst, src))


def _layout(size):
    """按尺寸给一套几何参数。

    小图标不能照搬大图：16px 下三道弧只有 0.6px 宽，会糊成一团噪点。
    所以 24px 及以下只保留电池本体（居中放大、笔画加粗），32-48px 用两道弧，
    64px 以上才画完整的三道弧。
    """
    if size <= 24:
        return dict(body_cx=0.500, body_cy=0.535, body_hw=0.205, body_hh=0.300,
                    body_r=0.070, stroke=0.090, nub_cy=0.200, nub_hh=0.042,
                    nub_hw=0.075, arcs=(), arc_cx=0.5, arc_cy=0.5, arc_w=0.0)
    if size <= 48:
        return dict(body_cx=0.372, body_cy=0.520, body_hw=0.163, body_hh=0.275,
                    body_r=0.062, stroke=0.068, nub_cy=0.205, nub_hh=0.045,
                    nub_hw=0.062, arcs=(0.120, 0.238), arc_cx=0.485,
                    arc_cy=0.600, arc_w=0.048)
    return dict(body_cx=0.355, body_cy=0.520, body_hw=0.150, body_hh=0.265,
                body_r=0.058, stroke=0.052, nub_cy=0.213, nub_hh=0.043,
                nub_hw=0.058, arcs=(0.108, 0.175, 0.242), arc_cx=0.500,
                arc_cy=0.600, arc_w=0.040)


def render(size):
    """渲染一张 size×size 的 RGBA 位图（行优先，返回 bytes）。"""
    s = float(size)
    soft = 1.15 / s          # 1px 左右过渡
    px = bytearray(size * size * 4)

    g = _layout(size)
    body_cx, body_cy = g["body_cx"], g["body_cy"]
    body_hw, body_hh = g["body_hw"], g["body_hh"]
    body_r, stroke = g["body_r"], g["stroke"]
    nub_cy, nub_hh, nub_hw = g["nub_cy"], g["nub_hh"], g["nub_hw"]
    arc_cx, arc_cy, arc_w = g["arc_cx"], g["arc_cy"], g["arc_w"]

    inner_top = body_cy - body_hh + stroke
    inner_bottom = body_cy + body_hh - stroke
    inner_h = inner_bottom - inner_top
    fill_top = inner_bottom - inner_h * BATTERY_LEVEL

    for y in range(size):
        v = (y + 0.5) / s
        # 底色竖向渐变
        t = _clamp(v)
        plate_rgb = tuple(int(round(a + (b - a) * t))
                          for a, b in zip(PLATE_TOP, PLATE_BOTTOM))
        for x in range(size):
            u = (x + 0.5) / s

            # 1) 圆角方块底
            a_plate = _alpha(sd_round_rect(u, v, 0.5, 0.5, 0.5, 0.5, 0.225), soft)
            if a_plate <= 0.0:
                continue
            rgb = plate_rgb
            alpha = a_plate

            # 2) 电池外壳（描边 = 实心圆角矩形减去内缩圆角矩形）
            d_body = sd_round_rect(u, v, body_cx, body_cy, body_hw, body_hh, body_r)
            d_inner = sd_round_rect(u, v, body_cx, body_cy,
                                    body_hw - stroke, body_hh - stroke,
                                    max(body_r - stroke, 0.01))
            d_shell = max(d_body, -d_inner)
            a_shell = _alpha(d_shell, soft)

            # 3) 电池正极凸起
            d_nub = sd_round_rect(u, v, body_cx, nub_cy, nub_hw, nub_hh,
                                  min(nub_hw, nub_hh) * 0.55)
            a_nub = _alpha(d_nub, soft)

            # 4) 电量填充（内腔下部）
            if v >= fill_top - soft:
                a_fill = _alpha(max(d_inner, fill_top - v), soft)
            else:
                a_fill = 0.0

            # 5) 信号弧
            a_arc = 0.0
            if g["arcs"] and u > arc_cx - 0.02:
                for radius in g["arcs"]:
                    a_arc = max(a_arc, _alpha(
                        sd_arc(u, v, arc_cx, arc_cy, radius, arc_w, -50, 50), soft))

            a_glyph = max(a_shell, a_nub, a_fill, a_arc)
            if a_glyph > 0.0:
                rgb = _over(rgb, GLYPH, a_glyph)

            i = (y * size + x) * 4
            px[i:i + 4] = bytes((rgb[0], rgb[1], rgb[2],
                                 int(round(alpha * 255))))
    return bytes(px)


def write_png(path, w, h, rgba):
    raw = b"".join(b"\x00" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def upscale(rgba, size, factor):
    """最近邻放大，方便肉眼看小尺寸的真实像素。"""
    out = bytearray()
    for y in range(size):
        row = rgba[y * size * 4:(y + 1) * size * 4]
        line = bytearray()
        for x in range(size):
            line += row[x * 4:x * 4 + 4] * factor
        out += line * factor
    return bytes(out)


def main():
    images = [(s, render(s)) for s in SIZES]
    ico_path = os.path.join(ROOT, "app.ico")
    with open(ico_path, "wb") as f:
        f.write(win_icon.build_ico(images))
    print(f"已生成 {ico_path}  ({os.path.getsize(ico_path)} 字节, "
          f"{len(SIZES)} 个尺寸: {', '.join(map(str, SIZES))})")

    preview = os.path.join(ROOT, "tools", "_icon_preview")
    os.makedirs(preview, exist_ok=True)
    for size, data in images:
        if size >= 256:
            write_png(os.path.join(preview, f"icon_{size}.png"), size, size, data)
        else:
            factor = max(1, 256 // size)
            write_png(os.path.join(preview, f"icon_{size}x{factor}.png"),
                      size * factor, size * factor,
                      upscale(data, size, factor))
    print("预览图:", preview)


if __name__ == "__main__":
    main()
