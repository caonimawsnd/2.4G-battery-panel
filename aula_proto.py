# -*- coding: utf-8 -*-
"""aula_proto.py —— 狼蛛（AULA）F87 三模键盘 2.4G 接收器（3554:FA09）

现状（2026-10-29 真机探测结论）：
1. 接收器枚举出 7 个接口；键盘用法在 0x0001:0x0006（in=9 与 in=21 两个）。
2. 厂商接口 0xFF02:0x0002（in=20/out=20）只接受 Output Report 0x13；
   原仓库 VXE 协议（report 0x08）被拒绝（err 87）。
3. 对 0x13 发送 ClickSync 的 ATK 16 字节电量帧（04 00 ... 49）无任何
   Input 回复；0xFF04:0x0002 的 Feature 0x06 只是 opcode 回显 +
   固定的 dongle 信息（e6 00 cd 83），不含电量。
4. **键盘未连接时全部接口静默**（接收器插着但没有外设配对时抓不到任何包）。

因此本模块目前只做两件事：
- 检测接收器是否存在、键盘是否在线（监听键盘接口有没有报文）；
- 电量解析留待「键盘连上后的抓包标定」——一旦键盘接入并发送状态包，
  用 tools/capture_live.py 抓到样本后即可在此补上解析逻辑。

只读实现：不写任何 Output / Feature。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

import hid_win as hw
from hid_win import HidDevice, HidError, HidInterface

VID = 0x3554
PID = 0xFA09
USAGE_PAGE_VENDOR = 0xFF02
USAGE_VENDOR = 0x0002
USAGE_KEYBOARD = 0x0006


@dataclass
class AulaInfo:
    dongle_present: bool = False
    keyboard_alive: bool = False     # 监听窗口内键盘侧有没有报文
    packets: int = 0
    samples: List[str] = field(default_factory=list)
    detail: str = ""


def _dongle_ifaces() -> List[HidInterface]:
    try:
        items = hw.enumerate_hid()
    except HidError:
        return []
    return [d for d in items if d.vid == VID and d.pid == PID]


def find_vendor_interface() -> Optional[HidInterface]:
    for d in _dongle_ifaces():
        if d.usage_page == USAGE_PAGE_VENDOR and d.usage == USAGE_VENDOR:
            return d
    return None


def read_info(listen: float = 2.0, stop_flag=None) -> AulaInfo:
    """探测接收器与键盘状态。

    返回的 info.detail 说明当前能确定到哪一步：
      - 没插接收器 / 接收器已插但键盘无报文 / 键盘有报文但协议未适配。
    """
    info = AulaInfo()
    ifaces = _dongle_ifaces()
    if not ifaces:
        info.detail = "没找到狼蛛 2.4G 接收器（3554:FA09）"
        return info
    info.dongle_present = True

    # 键盘在线检测：键盘用法接口（boot 9 字节那个） + 厂商接口
    targets = [d for d in ifaces
               if (d.usage == USAGE_KEYBOARD and d.usage_page == 0x0001
                   and d.input_len == 9)
               or (d.usage_page == USAGE_PAGE_VENDOR
                   and d.usage == USAGE_VENDOR and d.input_len)]
    try:
        devs = [HidDevice(d.path, write=False) for d in targets]
    except HidError as e:
        info.detail = f"无法打开接收器接口：{e}"
        return info
    try:
        deadline = time.monotonic() + listen
        while time.monotonic() < deadline:
            if stop_flag is not None and stop_flag():
                break
            got = False
            for dev in devs:
                pkt = dev.read_input(timeout_ms=120, stop_flag=stop_flag)
                if pkt:
                    got = True
                    info.packets += 1
                    if len(info.samples) < 8:
                        info.samples.append(pkt.hex())
            if not got:
                time.sleep(0.05)
    except HidError as e:
        info.detail = f"监听失败：{e}"
    finally:
        for dev in devs:
            try:
                dev.close()
            except Exception:
                pass

    if info.packets:
        info.keyboard_alive = True
        info.detail = ("接收器已插入；键盘侧有报文（按下按键可触发），"
                       "但电量协议尚未适配——需要连上后抓包标定")
    else:
        info.detail = ("接收器已插入，但键盘侧没有任何报文——"
                       "请确认键盘已开机、模式开关拨到 2.4G 并与接收器配对；"
                       "连上后敲几个键再刷新")
    return info


def read_battery_only(timeout: float = 2.0,
                      stop_flag=None) -> tuple[Optional[int], str]:
    """轻量读取：目前协议未标定，返回 (None, 状态说明)。"""
    info = read_info(listen=timeout, stop_flag=stop_flag)
    return None, info.detail
