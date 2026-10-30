# -*- coding: utf-8 -*-
"""我的设备电量 —— 只显示雷柏鼠标 + 狼蛛键盘的简洁面板

用法：
    python my_devices.py            打开界面（默认自动刷新）
    python my_devices.py --once     命令行读一次就退出

界面只有两块卡片，各显示一个设备的电量，可自动刷新。
底层复用 battery.py / rapoo_proto.py 里已经验证过的协议。
"""

from __future__ import annotations

import argparse
import math
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
from dataclasses import dataclass
from typing import Optional

import rapoo_proto as rp
import aula_proto as ap
import tray_common as tc
import win_link


# ==========================================================================
# 读取层
# ==========================================================================
@dataclass
class Reading:
    title: str
    subtitle: str
    level: Optional[int] = None
    status: str = ""
    detail: str = ""
    error: str = ""
    extra: str = ""
    dpi: Optional[int] = None     # 当前 DPI（雷柏状态广播上报）

    @property
    def ok(self) -> bool:
        return self.level is not None


def read_rapoo() -> Reading:
    """雷柏 2.4G 无线鼠标（24AE:184C，被动状态广播）。"""
    r = Reading("雷柏鼠标", "未连接")
    try:
        info = rp.read_info(listen=10.0)
    except Exception as e:
        r.error = f"读取出错：{e}"
        return r
    if not info.online:
        r.error = info.detail or "没找到雷柏接收器"
        return r
    r.subtitle = f"{rp.VID:04X}:184C · 雷柏 Gaming Device"
    r.level = info.battery
    r.dpi = info.dpi
    r.status = ""
    r.detail = "私有状态广播（BB B0：电量 + 当前 DPI + 连接模式）"
    r.extra = info.detail
    return r


def read_aula() -> Reading:
    """狼蛛 F87 三模键盘（2.4G 接收器 3554:FA09）。"""
    r = Reading("狼蛛 F87 键盘", "未连接")
    try:
        info = ap.read_info(listen=2.0)
    except Exception as e:
        r.error = f"读取出错：{e}"
        return r
    if not info.dongle_present:
        r.error = info.detail or "没找到 2.4G 接收器"
        return r
    r.subtitle = f"{ap.VID:04X}:{ap.PID:04X} · 2.4G Wireless Receiver"
    if info.keyboard_alive:
        # 键盘在线但电量协议还没标定出来
        r.error = info.detail
        r.extra = "样本：" + "  ".join(info.samples[:3]) if info.samples else ""
    else:
        r.error = info.detail
    return r


def read_all() -> list[Reading]:
    return [read_rapoo(), read_aula()]


# ==========================================================================
# 命令行模式
# ==========================================================================
def cli_once() -> None:
    for r in read_all():
        if r.ok:
            print(f"{r.title}: {r.level}%   {r.detail}")
            if r.extra:
                print(f"    {r.extra}")
        else:
            print(f"{r.title}: 读取失败 —— {r.error}")


# ==========================================================================
# 界面：设计令牌（浅色中性、克制配色、低视觉噪音）
# ==========================================================================
BG           = "#f0f3f7"   # 窗口底色（冷灰）
SURFACE      = "#ffffff"   # 卡片表面
SURFACE_2    = "#f2f5f9"   # 次级填充 / 悬停
TRACK        = "#e8edf3"   # 进度槽 / 电池内槽
BORDER       = "#dde3ec"   # 细边框
BORDER_SOFT  = "#edf1f6"   # 分隔线
SHADOW       = "#e3e8f0"   # 浅阴影
TEXT         = "#1f2937"
TEXT_MUTED   = "#5f6b7c"
TEXT_FAINT   = "#98a3b3"
ACCENT       = "#1f6feb"   # 主色：蓝色（强调 / 按钮 / 开关）
ACCENT_HOVER = "#1a5fd0"
ACCENT_MUTED = "#b6c9e6"   # 主色禁用态

FONT        = ("Microsoft YaHei UI", 10)
FONT_SM     = ("Microsoft YaHei UI", 9)
FONT_TINY   = ("Microsoft YaHei UI", 8)
FONT_BTN    = ("Microsoft YaHei UI", 9)
FONT_H1     = ("Microsoft YaHei UI", 18, "bold")
FONT_CARD   = ("Microsoft YaHei UI", 12, "bold")
FONT_DIALOG = ("Microsoft YaHei UI", 12, "bold")
FONT_NUM    = ("Segoe UI", 32, "bold")
FONT_PCT    = ("Segoe UI", 12, "bold")

RADIUS_CARD = 18
RADIUS_CTRL = 10

# 电量档位：(阈值, 主色, 胶囊底色, 胶囊文字色)，饱和度刻意压低，长时间看不刺眼
LEVEL_TONES = [
    (60, "#3f855c", "#edf6f1", "#2f6b48"),
    (30, "#a87a2c", "#fbf5e8", "#87631f"),
    (0,  "#b3544d", "#fbefed", "#93443e"),
]


def level_tone(level: Optional[int]) -> tuple[str, str, str]:
    if level is None:
        return TEXT_FAINT, SURFACE_2, TEXT_MUTED
    for threshold, color, soft, ink in LEVEL_TONES:
        if level >= threshold:
            return color, soft, ink
    return LEVEL_TONES[-1][1:]


# DPI 缩放因子，build_ui 里调用 tc.enable_dpi_awareness() 后更新
UI_SCALE = 1.0


def S(v: float) -> int:
    """按 DPI 缩放像素尺寸；字体是磅值，Tk 自动跟随，无需处理。"""
    return int(round(v * UI_SCALE))


def _rounded_points(x1: float, y1: float, x2: float, y2: float,
                    r: float, steps: int = 6) -> list[float]:
    """顺时针采样圆角矩形的边界点，转角用正弦/余弦细分，避免锯齿直角。"""
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    corners = [
        (x1 + r, y1 + r, 180, 270),
        (x2 - r, y1 + r, 270, 360),
        (x2 - r, y2 - r, 0, 90),
        (x1 + r, y2 - r, 90, 180),
    ]
    pts: list[float] = []
    for cx, cy, a1, a2 in corners:
        for i in range(steps + 1):
            a = math.radians(a1 + (a2 - a1) * i / steps)
            pts.extend((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _round_rect(canvas: "tk.Canvas", x1: float, y1: float, x2: float, y2: float,
                r: float, **kw) -> int:
    # 显式给出 fill/outline 默认值：多边形在不指定 fill 时会被填成黑色
    kw.setdefault("outline", "")
    kw.setdefault("fill", "")
    return canvas.create_polygon(_rounded_points(x1, y1, x2, y2, r), **kw)


# ==========================================================================
# 界面：自绘控件（纯 tkinter，无第三方依赖）
# ==========================================================================
class Card(tk.Frame):
    """白底大圆角卡片：底部一层极浅阴影 + 1px 细边框，内部用 body 放内容。"""

    def __init__(self, parent, radius: float = RADIUS_CARD,
                 pad: tuple[int, int, int, int] = (20, 18, 20, 18), bg: str = BG):
        super().__init__(parent, bg=bg)
        self.radius = S(radius)
        self._hover = False
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=SURFACE)
        self.body.pack(fill="both", expand=True,
                       padx=(S(pad[0]), S(pad[2])), pady=(S(pad[1]), S(pad[3])))
        self.canvas.bind("<Configure>", self._paint)

    def _paint(self, _event=None) -> None:
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 8 or h < 8:
            return
        c.delete("all")
        _round_rect(c, 1, 4, w - 1, h, self.radius,
                    fill="#dde6f4" if self._hover else SHADOW)
        _round_rect(c, 0, 0, w - 1, h - 4, self.radius,
                    fill=SURFACE,
                    outline="#c3d4ea" if self._hover else BORDER, width=1)

    def set_hover(self, on: bool) -> None:
        if self._hover == on:
            return
        self._hover = on
        self._paint()

    def bind_hover(self) -> None:
        """让卡片获得悬停反馈：子控件 Enter 会覆盖父级 Leave，不会闪烁。"""
        def enter(_event=None):
            self.set_hover(True)

        def leave(_event=None):
            self.set_hover(False)

        def walk(widget):
            widget.bind("<Enter>", enter, add="+")
            widget.bind("<Leave>", leave, add="+")
            for child in widget.winfo_children():
                walk(child)

        walk(self)


class Button(tk.Canvas):
    """统一圆角按钮：primary（唯一强调）/ secondary（默认）/ ghost。"""

    def __init__(self, parent, text: str, command=None, variant: str = "secondary",
                 bg: str = SURFACE, height: int = 36):
        self._font = tkfont.Font(font=FONT_BTN)
        self._text = text
        self._cmd = command
        self._variant = variant
        self._bg = bg
        self._height = S(height)
        self._enabled = True
        self._hover = False
        self._pressed = False
        self._width = self._font.measure(text) + S(34)
        super().__init__(parent, bg=bg, width=self._width, height=height,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._paint()

    def _colors(self) -> tuple[str, str, str]:
        if not self._enabled:
            if self._variant == "primary":
                return ACCENT_MUTED, "#f2f6fb", ACCENT_MUTED
            return SURFACE_2, TEXT_FAINT, BORDER
        if self._variant == "primary":
            fill = ACCENT_HOVER if (self._hover or self._pressed) else ACCENT
            return fill, "#ffffff", fill
        if self._variant == "ghost":
            fill = SURFACE_2 if (self._hover or self._pressed) else self._bg
            return fill, TEXT, fill
        fill = "#e9eef6" if (self._hover or self._pressed) else SURFACE
        return fill, TEXT, BORDER

    def _paint(self) -> None:
        self.delete("all")
        fill, fg, border = self._colors()
        _round_rect(self, 0, 0, self._width, self._height, S(RADIUS_CTRL),
                    fill=fill, outline=border, width=1)
        self.create_text(self._width / 2, self._height / 2,
                         text=self._text, fill=fg, font=FONT_BTN)

    def _on_press(self, event) -> None:
        if self._enabled:
            self._pressed = True
            self._paint()

    def _on_release(self, event) -> None:
        if not self._enabled:
            return
        clicked = (self._pressed
                   and 0 <= event.x <= self._width
                   and 0 <= event.y <= self._height)
        self._pressed = False
        self._paint()
        if clicked and self._cmd:
            self._cmd()

    def _on_enter(self, _event) -> None:
        if self._enabled:
            self._hover = True
            self._paint()

    def _on_leave(self, _event) -> None:
        self._hover = False
        self._pressed = False
        self._paint()

    def set_label(self, text: str) -> None:
        self._text = text
        self._width = self._font.measure(text) + S(34)
        self.configure(width=self._width)
        self._paint()

    def set_command(self, command) -> None:
        self._cmd = command

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._hover = False
        self._pressed = False
        self.configure(cursor="hand2" if enabled else "arrow")
        self._paint()


class Switch(tk.Canvas):
    """开关：圆角轨道 + 圆形滑块，点击即切换。"""

    W, H = 44, 24

    def __init__(self, parent, value: bool = False, command=None, bg: str = SURFACE):
        self._value = bool(value)
        self._cmd = command
        self.W, self.H = S(44), S(24)
        super().__init__(parent, bg=bg, width=self.W, height=self.H,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Button-1>", lambda _e: self.toggle())
        self._paint()

    def _paint(self) -> None:
        self.delete("all")
        track = ACCENT if self._value else "#d8dee7"
        _round_rect(self, 0, 0, self.W, self.H, self.H / 2, fill=track)
        r = S(8)
        cy = self.H / 2
        cx = self.W - S(4) - r if self._value else S(4) + r
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#ffffff",
                         outline="" if self._value else "#ccd4df", width=1)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)
        self._paint()

    def toggle(self) -> None:
        self._value = not self._value
        self._paint()
        if self._cmd:
            self._cmd()


class Select(tk.Canvas):
    """圆角下拉选择：自绘按钮 + 自绘圆角弹层（替代直角 Combobox）。"""

    def __init__(self, parent, values: list[str], value: str, on_change=None,
                 bg: str = SURFACE, width: int = 126, height: int = 34):
        width, height = S(width), S(height)
        super().__init__(parent, bg=bg, width=width, height=height,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._values = list(values)
        self._value = value
        self._on_change = on_change
        self._width = width
        self._hover = False
        self._popup: Optional[tk.Toplevel] = None
        self.bind("<Button-1>", lambda _e: self._open())
        self.bind("<Configure>", lambda _e: self._paint())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self._paint()

    def _set_hover(self, on: bool) -> None:
        if self._hover != on:
            self._hover = on
            self._paint()

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        if value in self._values:
            self._value = value
            self._paint()

    def _paint(self) -> None:
        self.delete("all")
        w = self._width
        h = self.winfo_height() or S(34)
        _round_rect(self, 0, 0, w, h, S(RADIUS_CTRL),
                    fill=SURFACE_2 if self._hover else SURFACE,
                    outline="#c3d4ea" if self._hover else BORDER, width=1)
        self.create_text(S(13), h / 2, text=self._value, anchor="w",
                         fill=TEXT, font=FONT_SM)
        x, y = w - S(18), h / 2
        self.create_line(x - 4, y - 2, x, y + 2, fill=TEXT_MUTED, width=1)
        self.create_line(x, y + 2, x + 4, y - 2, fill=TEXT_MUTED, width=1)

    def _open(self) -> None:
        if self._popup is not None:
            return
        w = self._width
        rowh, pad, gap = S(34), S(6), S(2)
        h = pad * 2 + rowh * len(self._values) + gap
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + S(6)
        if y + h > self.winfo_screenheight() - S(48):
            y = self.winfo_rooty() - h - S(6)

        top = tk.Toplevel(self)
        top.overrideredirect(True)
        top.configure(bg=SURFACE)
        top.geometry(f"{w}x{h}+{x}+{y}")
        top.attributes("-topmost", True)
        cv = tk.Canvas(top, bg=SURFACE, highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True)
        _round_rect(cv, 1, 1, w - 1, h - 1, S(12), fill=SURFACE,
                    outline=BORDER, width=1)

        def choose(index: int):
            value = self._values[index]
            self._close()
            self._value = value
            self._paint()
            if self._on_change:
                self._on_change(value)
            return "break"

        for i, value in enumerate(self._values):
            tag = f"row{i}"
            y1 = pad + gap + i * rowh
            y2 = y1 + rowh - gap
            selected = value == self._value
            _round_rect(cv, S(8), y1, w - S(8), y2, S(8),
                        fill=SURFACE_2 if selected else SURFACE, tags=(tag,))

            def on_enter(_event, t=tag):
                for item in cv.find_withtag(t):
                    if cv.type(item) == "polygon":
                        cv.itemconfigure(item, fill=SURFACE_2)

            def on_leave(_event, t=tag, sel=selected):
                for item in cv.find_withtag(t):
                    if cv.type(item) == "polygon":
                        cv.itemconfigure(item, fill=SURFACE_2 if sel else SURFACE)

            cv.create_text(S(22), (y1 + y2) / 2, text=value, anchor="w",
                           fill=ACCENT if selected else TEXT, font=FONT_SM,
                           tags=(tag,))
            cv.tag_bind(tag, "<Enter>", on_enter)
            cv.tag_bind(tag, "<Leave>", on_leave)
            cv.tag_bind(tag, "<Button-1>", lambda _event, idx=i: choose(idx))

        cv.bind("<Button-1>", lambda _e: self._close())
        top.bind("<Escape>", lambda _e: self._close())
        self._popup = top
        try:
            top.grab_set()
            top.focus_force()
        except Exception:
            pass

    def _close(self) -> None:
        popup = self._popup
        self._popup = None
        if popup is None:
            return
        try:
            popup.grab_release()
        except Exception:
            pass
        try:
            popup.destroy()
        except Exception:
            pass


class Pill(tk.Canvas):
    """状态胶囊：高度固定的圆角小标签，宽度随文字自适应。"""

    H = 22

    def __init__(self, parent, bg: str = SURFACE):
        self.H = S(Pill.H)
        super().__init__(parent, bg=bg, width=S(52), height=self.H,
                         highlightthickness=0, bd=0)
        self._bg = bg
        self.set("", TEXT_MUTED, SURFACE_2)

    def set(self, text: str, fg: str, fill: str) -> None:
        font = tkfont.Font(font=FONT_TINY)
        width = max(S(44), font.measure(text) + S(20))
        self.configure(width=width)
        self.delete("all")
        if not text:
            return
        _round_rect(self, 0, 0, width, self.H, self.H / 2, fill=fill)
        self.create_text(width / 2, self.H / 2, text=text, fill=fg, font=FONT_TINY)


class DeviceGlyph(tk.Canvas):
    """设备类型图标（鼠标 / 键盘），纯线条绘制，不依赖图片资源。"""

    SIZE = 20

    def __init__(self, parent, kind: str, bg: str = SURFACE):
        self.SIZE = S(DeviceGlyph.SIZE)
        super().__init__(parent, width=self.SIZE, height=self.SIZE, bg=bg,
                         highlightthickness=0, bd=0)
        self._kind = kind
        self._color = TEXT_FAINT
        self._paint()

    def set_color(self, color: str) -> None:
        if color != self._color:
            self._color = color
            self._paint()

    def _paint(self) -> None:
        self.delete("all")
        c = self._color
        if self._kind == "keyboard":
            _round_rect(self, 1.5, 5.5, 18.5, 14.5, 2.5, outline=c, width=1)
            for x in (5.0, 10.0, 15.0):
                self.create_oval(x - 0.9, 8.3, x + 0.9, 10.1, fill=c, outline="")
            self.create_line(6, 12.3, 14, 12.3, fill=c, width=1)
        else:                                   # 鼠标
            _round_rect(self, 5.5, 1.5, 14.5, 18.5, 4.5, outline=c, width=1)
            self.create_line(10, 4.5, 10, 8.5, fill=c, width=1)
        if UI_SCALE != 1.0:                     # 图形按 20px 坐标系绘制，整体缩放
            self.scale("all", 0, 0, UI_SCALE, UI_SCALE)


class Meter(tk.Canvas):
    """圆角电量条：浅色槽 + 按电量着色的填充，数值变化时平滑过渡。"""

    H = 8

    def __init__(self, parent, bg: str = SURFACE):
        self.H = S(Meter.H)
        super().__init__(parent, bg=bg, height=self.H, highlightthickness=0, bd=0)
        self._value = 0.0
        self._shown = 0.0
        self._color = TRACK
        self._anim = None
        self.bind("<Configure>", lambda _e: self._paint())

    def set(self, value: float, color: str, animate: bool = True) -> None:
        target = max(0.0, min(100.0, float(value)))
        self._color = color
        self._value = target
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None
        if not animate:
            self._shown = target
            self._paint()
            return
        start = self._shown
        steps = 12

        def step(i: int = 1) -> None:
            self._anim = None
            ease = 1 - (1 - i / steps) ** 3      # easeOutCubic
            self._shown = start + (target - start) * ease
            self._paint()
            if i < steps:
                try:
                    self._anim = self.after(16, lambda: step(i + 1))
                except Exception:
                    self._anim = None

        step()

    def _paint(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.H
        if w < 4:
            return
        _round_rect(self, 0, 0, w, h, h / 2, fill=TRACK)
        if self._shown <= 0:
            return
        fill_w = max(h, (w - 2) * self._shown / 100.0)
        _round_rect(self, 1, 1, 1 + fill_w, h - 1, (h - 2) / 2, fill=self._color)


class BatteryWidget(tk.Canvas):
    """横向电池图标，圆角外壳，填充比例和颜色随电量变化。"""

    W, H, CAP = 44, 18, 5

    def __init__(self, parent, bg: str = SURFACE):
        self.W, self.H, self.CAP = S(44), S(18), S(5)
        super().__init__(parent, bg=bg, width=self.W + self.CAP + 1,
                         height=self.H, highlightthickness=0, bd=0)
        self._bg = bg
        self.update_icon(None, TEXT_FAINT)

    def update_icon(self, level: Optional[int], color: str) -> None:
        self.delete("all")
        w, h = self.W, self.H
        _round_rect(self, 0, 0, w, h, S(5), fill=SURFACE_2, outline=BORDER, width=1)
        if level is not None:
            _round_rect(self, w + S(2), h / 2 - S(4), w + self.CAP, h / 2 + S(4), S(2),
                        fill=color)
        else:
            _round_rect(self, w + S(2), h / 2 - S(4), w + self.CAP, h / 2 + S(4), S(2),
                        fill="#d5dce6")
        if level is None or level <= 0:
            return
        inner_w = max(S(4.0), (w - S(6)) * min(level, 100) / 100.0)
        _round_rect(self, S(3), S(3), S(3) + inner_w, h - S(3), S(3), fill=color)
        # 两段刻线，让图标更像真实电池
        for k in (1, 2):
            x = S(3) + inner_w * k / 3
            if x < S(3) + inner_w - S(2):
                self.create_line(x, S(5), x, h - S(5), fill=SURFACE, width=1)


class DeviceCard:
    """一块设备卡片：状态点 + 名称 + 状态胶囊 / 大号百分比 / 电量条 / 详情。"""

    def __init__(self, parent, title: str, kind: str = "mouse"):
        self.card = Card(parent, bg=BG)
        body = self.card.body

        top = tk.Frame(body, bg=SURFACE)
        top.pack(fill="x")
        self.glyph = DeviceGlyph(top, kind, bg=SURFACE)
        self.glyph.pack(side="left")
        self.lab_title = tk.Label(top, text=title, bg=SURFACE, fg=TEXT,
                                  font=FONT_CARD)
        self.lab_title.pack(side="left", padx=(8, 0))
        self.pill = Pill(top, bg=SURFACE)
        self.pill.pack(side="right")

        self.lab_sub = tk.Label(body, text="正在读取…", bg=SURFACE,
                                fg=TEXT_FAINT, font=FONT_TINY, anchor="w",
                                justify="left")
        self.lab_sub.pack(fill="x", pady=(3, 0))

        mid = tk.Frame(body, bg=SURFACE)
        mid.pack(fill="x", pady=(12, 0))
        self.lab_num = tk.Label(mid, text="--", bg=SURFACE, fg=TEXT_FAINT,
                                font=FONT_NUM)
        self.lab_num.pack(side="left")
        self.lab_pct = tk.Label(mid, text="%", bg=SURFACE, fg=TEXT_MUTED,
                                font=FONT_PCT)
        self.lab_pct.pack(side="left", padx=(2, 0), pady=(0, 6), anchor="s")
        self.battery = BatteryWidget(mid, bg=SURFACE)
        self.battery.pack(side="right", pady=(0, 7), anchor="s")

        self.meter = Meter(body, bg=SURFACE)
        self.meter.pack(fill="x", pady=(12, 14))

        self.lab_detail = tk.Label(body, text="正在读取…", bg=SURFACE,
                                   fg=TEXT_MUTED, font=FONT_TINY,
                                   anchor="w", justify="left")
        self.lab_detail.pack(fill="x")
        self.lab_extra = tk.Label(body, text="", bg=SURFACE, fg=TEXT_FAINT,
                                  font=FONT_TINY, anchor="w", justify="left")
        self.lab_extra.pack(fill="x", pady=(3, 0))

        body.bind("<Configure>", self._rewrap)
        self.glyph.set_color(TEXT_MUTED)
        self._show_pct(False)
        self.card.bind_hover()

    def _show_pct(self, visible: bool) -> None:
        """没有读数时藏掉「%」，避免出现「-- %」这种别扭的占位。"""
        if visible and not self.lab_pct.winfo_manager():
            self.lab_pct.pack(side="left", padx=(2, 0), pady=(0, 6), anchor="s")
        elif not visible and self.lab_pct.winfo_manager():
            self.lab_pct.pack_forget()

    def _rewrap(self, event) -> None:
        width = max(160, event.width - 2)
        self.lab_sub.configure(wraplength=width)
        self.lab_detail.configure(wraplength=width)
        self.lab_extra.configure(wraplength=width)

    def update(self, r: Reading) -> None:
        self.lab_sub.configure(text=r.subtitle)
        if r.ok:
            color, soft, ink = level_tone(r.level)
            self.lab_num.configure(text=str(r.level), fg=color)
            self.glyph.set_color(color)
            self._show_pct(True)
            status = r.status if r.status not in ("未知", "状态未知") else ""
            self.pill.set(status or "在线", ink, soft)
            self.meter.set(r.level or 0, color)
            self.battery.update_icon(r.level, color)
            self.lab_detail.configure(text=r.detail)
            self.lab_extra.configure(text=r.extra)
        else:
            self.lab_num.configure(text="--", fg=TEXT_FAINT)
            self.glyph.set_color(TEXT_FAINT)
            self._show_pct(False)
            self.pill.set("未连接", TEXT_MUTED, SURFACE_2)
            self.meter.set(0, TRACK)
            self.battery.update_icon(None, TEXT_FAINT)
            self.lab_detail.configure(text=r.error)
            self.lab_extra.configure(text="")


class ScrollBody(tk.Frame):
    """内容超出可视高度时才可滚动的容器：细滚动条平时隐形，需要时出现。"""

    def __init__(self, parent, bg: str = BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner,
                                                 anchor="nw")
        self.bar = tk.Canvas(self, width=4, bg=bg, highlightthickness=0, bd=0)
        self.bar.place(relx=1.0, y=0, anchor="ne", relheight=1.0, x=-2)
        self._first, self._last = 0.0, 1.0
        self._drag_y = 0
        self._drag_first = 0.0
        self._drag_h = 1
        self.bar.bind("<Button-1>", self._drag_start)
        self.bar.bind("<B1-Motion>", self._drag_move)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.inner.bind("<Configure>", lambda _e: self._sync())

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._sync()

    def _sync(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._paint_bar()

    def _on_scroll(self, first: str, last: str) -> None:
        self._first, self._last = float(first), float(last)
        self._paint_bar()

    def _paint_bar(self) -> None:
        bar = self.bar
        bar.delete("all")
        height = bar.winfo_height()
        if height < 24 or (self._last - self._first) >= 0.999:
            return
        y1 = self._first * height + 2
        y2 = self._last * height - 2
        if y2 - y1 < 20:                      # 内容很长时保证滑块可抓
            y1 = max(2, (y1 + y2) / 2 - 10)
            y2 = y1 + 20
        _round_rect(bar, 0, y1, 4, y2, 2, fill="#ccd5e1")

    def _drag_start(self, event) -> None:
        self._drag_y = event.y
        self._drag_first = self._first
        self._drag_h = max(1, self.bar.winfo_height())

    def _drag_move(self, event) -> None:
        delta = (event.y - self._drag_y) / self._drag_h
        self.canvas.yview_moveto(max(0.0, min(1.0, self._drag_first + delta)))

    def scroll(self, direction: int) -> None:
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(direction, "units")


def show_dialog(parent, title: str, message: str) -> None:
    """统一圆角弹窗，替代系统直角消息框。"""
    top = tk.Toplevel(parent)
    top.overrideredirect(True)
    top.configure(bg=BG)
    try:
        top.transient(parent)
    except Exception:
        pass

    card = Card(top, radius=16, pad=(22, 20, 22, 18), bg=BG)
    card.pack(fill="both", expand=True, padx=8, pady=8)
    body = card.body
    tk.Label(body, text=title, bg=SURFACE, fg=TEXT, font=FONT_DIALOG,
             anchor="w").pack(fill="x")
    tk.Label(body, text=message, bg=SURFACE, fg=TEXT_MUTED, font=FONT_SM,
             anchor="w", justify="left", wraplength=360).pack(fill="x", pady=(8, 16))
    row = tk.Frame(body, bg=SURFACE)
    row.pack(fill="x")
    Button(row, "知道了", command=top.destroy, variant="primary",
           bg=SURFACE).pack(side="right")

    top.update_idletasks()
    width = max(380, card.winfo_reqwidth() + 16)
    height = card.winfo_reqheight() + 16
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
    top.geometry(f"{width}x{height}+{x}+{y}")
    top.bind("<Escape>", lambda _e: top.destroy())
    try:
        top.grab_set()
        top.focus_force()
    except Exception:
        pass


def build_ui():
    global UI_SCALE
    UI_SCALE = tc.enable_dpi_awareness()   # 必须在创建 Tk 窗口前声明，否则字体发糊
    root = tk.Tk()
    root.title(tc.UI_TITLE)
    root.configure(bg=BG)
    root.minsize(S(560), S(520))
    # 屏幕居中打开（水平居中、垂直略偏上，别贴边）
    win_w, win_h = S(780), S(660)
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    win_w = min(win_w, screen_w - 80)
    win_h = min(win_h, screen_h - 120)
    root.geometry(f"{win_w}x{win_h}"
                  f"+{max(0, (screen_w - win_w) // 2)}"
                  f"+{max(0, (screen_h - win_h) // 3)}")

    # 窗口 / 任务栏图标（打包后图标在 _MEIPASS 里，脚本模式在源码目录）
    try:
        ico = tc.resource_path("app.ico")
        if os.path.exists(ico):
            root.iconbitmap(default=ico)
    except Exception:
        pass

    state = {"busy": False, "auto": True, "interval": 60, "after_id": None,
             "starting": False, "started_at": 0.0}
    # Tkinter 不是线程安全的：后台线程只往队列里放结果，主线程统一取出来处理
    results: "queue.Queue[tuple]" = queue.Queue()

    cfg = tc.load_config()
    state["interval"] = int(cfg["interval"])
    current_label = dict((sec, label) for sec, label in tc.INTERVAL_CHOICES).get(
        state["interval"], "1 分钟")

    # ---- 顶部 ----
    head = tk.Frame(root, bg=BG)
    head.pack(fill="x", padx=24, pady=(20, 14))

    title_box = tk.Frame(head, bg=BG)
    title_box.pack(side="left")
    tk.Label(title_box, text=tc.UI_TITLE, bg=BG, fg=TEXT,
             font=FONT_H1).pack(anchor="w")
    tk.Label(title_box, text="2.4G 无线外设 · 电量监控", bg=BG, fg=TEXT_MUTED,
             font=FONT_SM).pack(anchor="w", pady=(4, 0))

    actions = tk.Frame(head, bg=BG)
    actions.pack(side="right")

    def on_auto():
        state["auto"] = switch_auto.get()
        _reschedule()

    auto_label = tk.Label(actions, text="自动刷新", bg=BG, fg=TEXT_MUTED,
                          font=FONT_SM, cursor="hand2")
    auto_label.pack(side="left", padx=(0, 8))
    switch_auto = Switch(actions, value=True, command=on_auto, bg=BG)
    switch_auto.pack(side="left")
    auto_label.bind("<Button-1>", lambda _e: switch_auto.toggle())

    btn_refresh = Button(actions, "立即刷新", variant="primary", bg=BG)
    btn_refresh.pack(side="left", padx=(14, 0))

    # ---- 底部状态（先占底，body 再填充剩余空间）----
    foot = tk.Frame(root, bg=BG)
    foot.pack(side="bottom", fill="x", padx=24, pady=(6, 14))
    foot_dot = tk.Canvas(foot, width=8, height=8, bg=BG,
                         highlightthickness=0, bd=0)
    foot_dot.pack(side="left", pady=(2, 0))
    foot_lab = tk.Label(foot, text="正在读取…", bg=BG, fg=TEXT_MUTED,
                        font=FONT_SM, anchor="w")
    foot_lab.pack(side="left", padx=(8, 0))
    foot_meta = tk.Label(foot, text="", bg=BG, fg=TEXT_FAINT, font=FONT_TINY)
    foot_meta.pack(side="right")

    def foot_status(ok_count: int) -> None:
        color = {2: LEVEL_TONES[0][1], 1: LEVEL_TONES[1][1]}.get(
            ok_count, LEVEL_TONES[2][1])
        foot_dot.delete("all")
        foot_dot.create_oval(0, 0, 7, 7, fill=color, outline="")

    # ---- 主体（可滚动）----
    scroll = ScrollBody(root, bg=BG)
    scroll.pack(fill="both", expand=True, padx=24)

    holder = tk.Frame(scroll.inner, bg=BG)
    holder.pack(fill="x")

    card_atk = DeviceCard(holder, "雷柏鼠标", kind="mouse")
    card_dr = DeviceCard(holder, "狼蛛 F87 键盘", kind="keyboard")

    layout_state = {"two": None}

    def layout_cards(two: bool) -> None:
        card_atk.card.grid_forget()
        card_dr.card.grid_forget()
        if two:
            holder.columnconfigure(0, weight=1, uniform="card")
            holder.columnconfigure(1, weight=1, uniform="card")
            holder.rowconfigure(0, weight=1)
            card_atk.card.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
            card_dr.card.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        else:
            holder.columnconfigure(0, weight=1, uniform="")
            holder.columnconfigure(1, weight=0, uniform="")
            holder.rowconfigure(0, weight=0)
            card_atk.card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
            card_dr.card.grid(row=1, column=0, sticky="ew")

    # ---- 设置 ----
    set_card = Card(scroll.inner, pad=(20, 18, 20, 18), bg=BG)
    set_card.pack(fill="x", pady=(16, 6))
    sbody = set_card.body

    tk.Label(sbody, text="设置", bg=SURFACE, fg=TEXT,
             font=FONT_CARD).pack(anchor="w")

    row_a = tk.Frame(sbody, bg=SURFACE)
    row_a.pack(fill="x", pady=(14, 0))
    tk.Label(row_a, text="刷新间隔", bg=SURFACE, fg=TEXT_MUTED,
             font=FONT_SM).pack(side="left")

    def on_interval(label: str):
        mapping = dict((name, sec) for sec, name in tc.INTERVAL_CHOICES)
        sec = mapping.get(label, 60)
        cfg["interval"] = sec
        tc.save_config(cfg)
        state["interval"] = sec
        tc.post_to_tray(tc.MSG_RELOAD)      # 让托盘立刻换间隔
        update_meta()
        _reschedule()
        refresh()

    sel_interval = Select(row_a, [name for _sec, name in tc.INTERVAL_CHOICES],
                          current_label, on_interval, bg=SURFACE)
    sel_interval.pack(side="left", padx=(10, 0))

    tk.Label(row_a, text="开机自启", bg=SURFACE, fg=TEXT_MUTED,
             font=FONT_SM).pack(side="left", padx=(22, 8))

    def on_boot():
        want = switch_boot.get()
        ok = tc.set_autostart(want)
        cfg["autostart"] = want
        tc.save_config(cfg)
        tc.post_to_tray(tc.MSG_RELOAD)
        if want and not ok:
            notify("开机自启设置失败：无法创建启动文件夹快捷方式")
        elif want:
            notify("已加入开机自启（任务管理器 →「启动」标签里能看到 电量托盘）", 12)
        else:
            notify("已取消开机自启")

    switch_boot = Switch(row_a, value=tc.is_autostart_enabled(),
                         command=on_boot, bg=SURFACE)
    switch_boot.pack(side="left")

    tk.Frame(sbody, bg=BORDER_SOFT, height=1).pack(fill="x", pady=(16, 14))

    tray_row = tk.Frame(sbody, bg=SURFACE)
    tray_row.pack(fill="x")
    tray_dot = tk.Canvas(tray_row, width=8, height=8, bg=SURFACE,
                         highlightthickness=0, bd=0)
    tray_dot.pack(side="left", pady=(4, 0))
    lab_tray = tk.Label(tray_row, text="", bg=SURFACE, fg=TEXT_MUTED,
                        font=FONT_SM, anchor="w", justify="left")
    lab_tray.pack(side="left", padx=(8, 0), fill="x", expand=True)

    def refresh_tray_state():
        running = tc.is_tray_running()
        tray_dot.delete("all")
        tray_dot.create_oval(0, 0, 7, 7,
                             fill=LEVEL_TONES[0][1] if running else TEXT_FAINT,
                             outline="")
        if state.get("starting"):
            return                              # 正在启动，别覆盖提示文字
        if state.get("notice") and time.time() < state.get("notice_until", 0):
            lab_tray.configure(text=state["notice"])   # 临时提示优先显示
            btn_tray.set_enabled(True)
            btn_tray.set_label("退出托盘程序" if running else "启动托盘程序")
            return
        state["notice"] = ""
        btn_tray.set_enabled(True)
        btn_tray.set_label("退出托盘程序" if running else "启动托盘程序")
        lab_tray.configure(text="托盘运行中：右键托盘图标即可打开本窗口"
                                if running else "托盘未运行：不会后台自动刷新")

    tray_actions = tk.Frame(sbody, bg=SURFACE)
    tray_actions.pack(fill="x", pady=(14, 0))

    def notify(text: str, seconds: float = 8.0) -> None:
        """在状态标签上显示一条临时提示。"""
        state["notice"] = text
        state["notice_until"] = time.time() + seconds
        refresh_tray_state()

    def tray_done(ok: bool):
        state["starting"] = False
        refresh_tray_state()
        if not ok:
            notify("启动失败：可双击桌面「电量托盘」再试", 12)

    def on_links():
        btn_link.set_enabled(False)
        btn_link.set_label("正在创建…")

        def work():
            try:
                r = tc.install_desktop_links()
            except Exception as e:
                traceback.print_exc()
                r = {"folder": "", "links": {}, "errors": [str(e)]}
            results.put(("links", r))

        threading.Thread(target=work, daemon=True).start()

    def links_done(r: dict):
        btn_link.set_enabled(True)
        btn_link.set_label("重建桌面链接")
        bits = []
        kind = r.get("folder") or ""
        if kind:
            bits.append(f"文件夹→{win_link.KIND_LABEL.get(kind, kind)}")
        for name, k in (r.get("links") or {}).items():
            bits.append(f"{name}→{win_link.KIND_LABEL.get(k, k)}")
        if bits:
            notify("桌面链接已更新：" + "；".join(bits), 12)
        else:
            notify("桌面链接创建失败", 12)
        if r.get("errors"):
            show_dialog(root, "桌面链接", "\n".join(r["errors"]))

    def on_tray_toggle():
        if tc.is_tray_running():
            tc.post_to_tray(tc.MSG_QUIT)
            for delay in (600, 1500, 3000):
                root.after(delay, refresh_tray_state)
            return

        # 启动要等托盘窗口真正出现（pythonw 是静默进程），放后台线程做，别卡界面
        state["starting"] = True
        state["started_at"] = time.time()
        btn_tray.set_enabled(False)
        btn_tray.set_label("正在启动…")
        lab_tray.configure(text="正在启动托盘程序…")

        def work():
            try:
                ok = tc.start_tray_app()
            except Exception:
                traceback.print_exc()
                ok = False
            results.put(("tray", ok))          # 交给主线程处理

        threading.Thread(target=work, daemon=True).start()

    btn_tray = Button(tray_actions, "退出托盘程序", command=on_tray_toggle,
                      variant="secondary", bg=SURFACE)
    btn_tray.pack(side="right")
    btn_link = Button(tray_actions, "重建桌面链接", command=on_links,
                      variant="secondary", bg=SURFACE)
    btn_link.pack(side="right", padx=(0, 8))
    refresh_tray_state()

    set_card.body.bind("<Configure>", lambda e: lab_tray.configure(
        wraplength=max(180, e.width - 30)))

    # ---- 刷新逻辑 ----
    def apply(readings: list[Reading]):
        card_atk.update(readings[0])
        card_dr.update(readings[1])
        ok = sum(1 for r in readings if r.ok)
        foot_status(ok)
        foot_lab.configure(text=f"更新于 {time.strftime('%H:%M:%S')} · "
                                f"成功读取 {ok}/2 个设备"
                                + ("" if state["auto"] else "（自动刷新已关闭）"))
        # 标题栏带上电量概览，任务栏悬停 / Alt+Tab 也能看到
        def brief(r: Reading) -> str:
            return f"{r.level}%" if r.ok else "--"

        root.title(f"{tc.UI_TITLE}  ·  鼠标 {brief(readings[0])}"
                   f"  键盘 {brief(readings[1])}")
        state["busy"] = False
        btn_refresh.set_enabled(True)

    def worker():
        try:
            readings = read_all()
        except Exception:
            traceback.print_exc()
            readings = [Reading("雷柏鼠标", "", error="读取异常"),
                        Reading("狼蛛 F87 键盘", "", error="读取异常")]
        results.put(("readings", readings))

    def refresh():
        if state["busy"]:
            return
        state["busy"] = True
        btn_refresh.set_enabled(False)
        foot_lab.configure(text="正在读取…（雷柏的电量广播要等几秒钟）")
        threading.Thread(target=worker, daemon=True).start()

    def _reschedule():
        if state["after_id"]:
            root.after_cancel(state["after_id"])
            state["after_id"] = None
        if state["auto"]:
            state["after_id"] = root.after(state["interval"] * 1000, _tick)

    def _tick():
        refresh()
        _reschedule()

    def update_meta():
        foot_meta.configure(
            text=f"刷新间隔 {sel_interval.get()} · 共 2 台设备 · F5 刷新")

    btn_refresh.set_command(refresh)
    update_meta()

    # 快捷键：F5 / Ctrl+R 立即刷新
    for seq in ("<F5>", "<Control-r>", "<Control-R>"):
        root.bind(seq, lambda _e: refresh())

    root.after(300, refresh)
    _reschedule()

    # ---- 响应式：窄窗口单列堆叠，宽窗口双列并排 ----
    def on_resize(_event=None):
        available = root.winfo_width() - 48
        two = available >= 620
        if two != layout_state["two"]:
            layout_state["two"] = two
            layout_cards(two)

    root.bind("<Configure>", on_resize)
    root.after(80, on_resize)
    layout_cards(True)

    # 滚轮只在指针位于内容区时生效
    def on_wheel(event):
        cx, cy = scroll.canvas.winfo_rootx(), scroll.canvas.winfo_rooty()
        inside = (cx <= event.x_root <= cx + scroll.canvas.winfo_width()
                  and cy <= event.y_root <= cy + scroll.canvas.winfo_height())
        if inside:
            scroll.scroll(-1 if event.delta > 0 else 1)

    root.bind_all("<MouseWheel>", on_wheel)

    # ---- 主线程统一处理后台线程的结果 + 跟随托盘状态 ----
    def pump():
        try:
            while True:
                kind, payload = results.get_nowait()
                if kind == "readings":
                    apply(payload)
                elif kind == "tray":
                    tray_done(payload)
                elif kind == "links":
                    links_done(payload)
        except queue.Empty:
            pass
        except Exception:
            traceback.print_exc()
            state["busy"] = False
            state["starting"] = False
            btn_refresh.set_enabled(True)

        # 兜底：启动流程万一卡住，20 秒后放开按钮，别让它永久禁用
        if state["starting"] and time.time() - state["started_at"] > 20:
            state["starting"] = False
            refresh_tray_state()

        refresh_tray_state()        # FindWindowW 很便宜，顺带同步托盘状态
        root.after(1000, pump)

    root.after(1000, pump)

    # 托盘右键打开时保证窗口到前台
    def raise_me():
        try:
            root.lift()
            root.focus_force()
        except Exception:
            pass

    root.after(250, raise_me)
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description="我的设备电量")
    parser.add_argument("--once", action="store_true", help="命令行读一次就退出")
    parser.add_argument("--install-links", action="store_true",
                        help="在桌面重建软连接（项目文件夹 + 启动脚本）")
    parser.add_argument("--autostart", choices=["on", "off", "status"],
                        help="开机自启：on 打开 / off 关闭 / status 查看")
    args = parser.parse_args()

    if args.install_links:
        r = tc.install_desktop_links()
        print("桌面链接：")
        print(f"  项目文件夹 {tc.DESKTOP_LINK_NAME} -> "
              f"{win_link.KIND_LABEL.get(r['folder'], r['folder'] or '创建失败')}")
        for name, kind in r["links"].items():
            print(f"  {name} -> {win_link.KIND_LABEL.get(kind, kind)}")
        for msg in r["errors"]:
            print("  注意：", msg)
        return

    if args.autostart:
        if args.autostart == "status":
            st = tc.autostart_status()
            print("开机自启：", "已启用" if st["enabled"] else "未启用")
            print("  方式：", st["method"])
            print("  快捷方式：", st["shortcut"],
                  "(存在)" if st["shortcut_exists"] else "(不存在)")
            print("  任务管理器状态：", st["taskmanager_state"])
            print("  目标：", st["target"])
            print("  旧注册表项：", "还在" if st["legacy_registry"] else "已清理")
        else:
            ok = tc.set_autostart(args.autostart == "on")
            print("已" + ("加入" if args.autostart == "on" else "取消") + "开机自启",
                  "" if ok else "（失败）")
        return

    if args.once:
        cli_once()
        return
    try:
        root = build_ui()
    except Exception:
        print("无法启动图形界面，改用命令行模式：")
        traceback.print_exc()
        cli_once()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
