# -*- coding: utf-8 -*-
"""rapoo_proto.py —— 雷柏（Rapoo）2.4G 无线鼠标电量读取（24AE:184C 实测逆向）

协议来源：真机抓包 + ClickSync (Nuitfanee/ClickSync) 的 Rapoo 驱动实现交叉验证。

已确认的事实：
1. 雷柏的电量是**被动广播**，无法通过主动指令触发
   （ClickSync 源码注释："不需要、也无法通过主动指令触发"，
    且真机探测 0x00-0x40 所有 Output Report ID 均被拒绝）。
2. 鼠标会在 0xFF00:0x0002 的 7 字节接口上周期性广播状态包（约 4~10 秒一包）：

       BB B0 02 40 06 01 XX

   末字节 XX（下标 6）随时间缓慢下降：跨约 50 分钟实测 0x24(36) -> 0x23(35)，
   是该包中唯一变化的字段，判定为电量百分比。
   （注意：ClickSync 里另一批雷柏机型用的是 8+ 字节、包头 0x20、电量在第 8
    字节的状态包；本机型（24AE:184C）不适用那个格式，两者不能混用。）
3. 若 10 秒内收不到广播，多半是鼠标休眠了，动一动鼠标即可唤醒。

只读实现：只打开 Input，绝不写任何 Output / Feature。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

import hid_win as hw
from hid_win import HidDevice, HidError, HidInterface

VID = 0x24AE
USAGE_PAGE = 0xFF00
USAGE = 0x0002
PKT_LEN = 7
IDX_BATTERY = 6


@dataclass
class RapooInfo:
    online: bool = False            # 是否收到过状态广播
    battery: Optional[int] = None   # 电量百分比（末字节）
    packets: int = 0                # 收到的状态包数量
    values: List[int] = field(default_factory=list)   # 依次读到的电量原始值
    detail: str = ""
    raw: bytes = b""


def find_interface() -> Optional[HidInterface]:
    """找 7 字节状态广播接口（0xFF00:0x0002, in=7）。

    注意同型号还有 in=12 的同 usage 接口（col06），实测它不广播状态包，
    所以必须按 input_len==7 精确匹配。
    """
    try:
        items = hw.enumerate_hid()
    except HidError:
        return None
    for d in items:
        if (d.vid == VID and d.usage_page == USAGE_PAGE
                and d.usage == USAGE and d.input_len == PKT_LEN):
            return d
    return None


def parse_packet(pkt: bytes) -> Optional[int]:
    """校验状态包签名并提取电量。合法返回 0-100，否则 None。"""
    if len(pkt) < PKT_LEN or pkt[0] != 0xBB or pkt[1] != 0xB0:
        return None
    v = pkt[IDX_BATTERY]
    return v if 0 <= v <= 100 else None


def read_info(listen: float = 10.0, stop_flag=None) -> RapooInfo:
    """监听状态广播直到拿到电量或超时。

    广播周期约 4~10 秒；打开接口后通常几秒内就有第一包。
    """
    info = RapooInfo()
    iface = find_interface()
    if iface is None:
        info.detail = "没找到雷柏接收器（24AE:184C）"
        return info
    try:
        dev = HidDevice(iface.path, write=False)
    except HidError as e:
        info.detail = f"无法打开接口：{e}"
        return info
    try:
        deadline = time.monotonic() + listen
        grace_until = None            # 拿到首包后再等一小段，收第二包交叉确认
        while time.monotonic() < deadline:
            if stop_flag is not None and stop_flag():
                break
            if grace_until is not None and time.monotonic() >= grace_until:
                break
            pkt = dev.read_input(timeout_ms=250, stop_flag=stop_flag)
            if not pkt:
                continue
            level = parse_packet(pkt)
            if level is None:
                continue
            info.online = True
            info.packets += 1
            info.values.append(level)
            if not info.raw:
                info.raw = pkt
            if info.battery is None:
                info.battery = level
                grace_until = time.monotonic() + 3.0
    except HidError as e:
        info.detail = f"监听失败：{e}"
    finally:
        try:
            dev.close()
        except Exception:
            pass
    if info.online:
        info.detail = (f"状态广播 x{info.packets}，电量读数 "
                       f"{info.values}（末字节，实测随时间缓降）")
    elif not info.detail:
        info.detail = "没有收到状态广播（鼠标可能休眠了，动一动鼠标再试）"
    return info


def read_battery_only(timeout: float = 10.0,
                      stop_flag=None) -> tuple[Optional[int], str]:
    """轻量读取：返回 (电量, 错误说明)，适合托盘轮询。"""
    info = read_info(listen=timeout, stop_flag=stop_flag)
    if info.battery is not None:
        return info.battery, ""
    return None, info.detail or "没有读到电量"
