# -*- coding: utf-8 -*-
"""win_mouse.py —— Windows 系统级鼠标设置 + 回报率实测

系统设置部分移植自雷柏官方 AHUB 2.0 驱动的 windowsMouseParams.ts
（koffi 调 user32.SystemParametersInfoW 的实现，这里用 ctypes 等价移植）：
  - 指针速度（1-20，默认 10）SPI_GETMOUSESPEED / SPI_SETMOUSESPEED
  - 滚轮一次滚动行数（1-100，-1=整页）SPI_GET/SETWHEELSCROLLLINES

回报率实测：打开接收器的标准鼠标接口（usage 0x0001:0x0002），
统计移动时 input report 的到达间隔换算 Hz。这是纯测量，不写设备。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Optional

import hid_win as hw
from hid_win import HidDevice, HidError

# ---- SPI 常量（与 AHUB windowsMouseParams.ts 一致）----
SPI_GETMOUSESPEED = 0x0070
SPI_SETMOUSESPEED = 0x0071
SPI_GETWHEELSCROLLLINES = 0x0068
SPI_SETWHEELSCROLLLINES = 0x0069
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02
SPIF_UPDATEANDSEND = SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
WHEEL_PAGESCROLL = 0xFFFFFFFF

MOUSE_SPEED_MIN, MOUSE_SPEED_MAX = 1, 20
WHEEL_LINES_MIN, WHEEL_LINES_MAX = 1, 100
WHEEL_PAGE = -1

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_SystemParametersInfoW = _user32.SystemParametersInfoW
_SystemParametersInfoW.restype = wintypes.BOOL
_SystemParametersInfoW.argtypes = [
    wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]


def _get_uint(spi_action: int) -> Optional[int]:
    out = wintypes.UINT(0)
    if not _SystemParametersInfoW(spi_action, 0, ctypes.byref(out), 0):
        return None
    return out.value


def get_pointer_speed() -> Optional[int]:
    """指针速度 1-20（默认 10）；失败返回 None。"""
    try:
        v = _get_uint(SPI_GETMOUSESPEED)
        if v is None:
            return None
        v = int(v)
        return v if MOUSE_SPEED_MIN <= v <= MOUSE_SPEED_MAX else None
    except Exception:
        return None


def set_pointer_speed(speed: int) -> bool:
    """设置指针速度 1-20。"""
    speed = int(speed)
    if not MOUSE_SPEED_MIN <= speed <= MOUSE_SPEED_MAX:
        return False
    # 实测（AHUB 注释同款坑）：pvParam 直接传速度整数值，而不是指向 int 的指针
    return bool(_SystemParametersInfoW(
        SPI_SETMOUSESPEED, 0, wintypes.LPVOID(speed), SPIF_UPDATEANDSEND))


def get_wheel_scroll_lines() -> Optional[int]:
    """滚轮一次滚动行数；整页返回 -1；失败 None。"""
    try:
        v = _get_uint(SPI_GETWHEELSCROLLLINES)
        if v is None:
            return None
        if v == WHEEL_PAGESCROLL:
            return WHEEL_PAGE
        v = int(v)
        return v if WHEEL_LINES_MIN <= v <= WHEEL_LINES_MAX else None
    except Exception:
        return None


def set_wheel_scroll_lines(lines: int) -> bool:
    """设置滚轮滚动行数 1-100，或 -1 表示整页。"""
    lines = int(lines)
    if lines == WHEEL_PAGE:
        actual = WHEEL_PAGESCROLL
    elif WHEEL_LINES_MIN <= lines <= WHEEL_LINES_MAX:
        actual = lines
    else:
        return False
    return bool(_SystemParametersInfoW(
        SPI_SETWHEELSCROLLLINES, actual, None, SPIF_UPDATEANDSEND))


def get_mouse_sys() -> dict:
    return {
        "pointer_speed": get_pointer_speed(),
        "wheel_lines": get_wheel_scroll_lines(),
    }


# ---- 回报率实测 ----------------------------------------------------------

def find_mouse_iface():
    """找接收器上的标准鼠标接口（usage 0x0001:0x0002）。"""
    try:
        items = hw.enumerate_hid()
    except HidError:
        return None
    for d in items:
        if (d.vid == 0x24AE and d.usage_page == 0x0001
                and d.usage == 0x0002 and 0 < d.input_len <= 16):
            return d
    return None


def measure_polling_rate(seconds: float = 2.0,
                         stop_flag=None) -> dict:
    """测量回报率：统计鼠标移动时的 input report 到达间隔。

    返回 {hz, samples, moved}。需要测量期间移动/晃动鼠标；
    没有移动时 moved=False、hz=0。
    """
    iface = find_mouse_iface()
    if iface is None:
        return {"hz": 0, "samples": 0, "moved": False,
                "error": "没找到接收器的鼠标接口"}
    try:
        dev = HidDevice(iface.path)
    except HidError as e:
        return {"hz": 0, "samples": 0, "moved": False, "error": str(e)}
    stamps = []
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if stop_flag is not None and stop_flag():
                break
            pkt = dev.read_input(timeout_ms=100)
            if pkt:
                stamps.append(time.perf_counter())
    except HidError as e:
        return {"hz": 0, "samples": 0, "moved": False, "error": str(e)}
    finally:
        try:
            dev.close()
        except Exception:
            pass
    # 静止时鼠标不再上报；间隔 < 4ms 的连击才是有效回报样本
    deltas = [b - a for a, b in zip(stamps, stamps[1:]) if 0.0002 < b - a < 0.008]
    moved = len(stamps) >= 10
    if len(deltas) >= 10:
        deltas.sort()
        median = deltas[len(deltas) // 2]
        hz = round(1.0 / median)
    else:
        hz = 0
    return {"hz": hz, "samples": len(deltas) + 1, "moved": moved,
            "error": "" if moved else "测量期间没有检测到鼠标移动，请晃动鼠标再试"}
