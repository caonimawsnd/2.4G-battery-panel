# -*- coding: utf-8 -*-
"""tools/probe_deep.py —— 探测厂商接口接受的 Report ID + 长时间抓包。

注意：会向厂商接口写入"全 0 Output Report"来探测合法 Report ID，
这是逆向的常规手段，全 0 载荷通常无害；但若你担心，可跳过本脚本。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import hid_win as hw
import battery as bt


def find(vid, usage_page=None, usage=None):
    return [d for d in hw.enumerate_hid()
            if d.vid == vid
            and (usage_page is None or d.usage_page == usage_page)
            and (usage is None or d.usage == usage)]


def probe_ids(iface, max_id=0x40):
    print(f"\n=== 探测 Report ID {iface.vid_pid} usage={iface.describe_usage()} (in={iface.input_len}) ===")
    try:
        ids = bt.probe_report_ids(iface, max_id)
        print(f"    接受的 Report ID: {[hex(i) for i in ids]}")
        return ids
    except hw.HidError as e:
        print(f"    打开失败：{e}")
        return []


def capture_timed(iface, seconds):
    print(f"\n=== 带时间戳抓包 {iface.vid_pid} usage={iface.describe_usage()} ({seconds}s) ===")
    try:
        with hw.HidDevice(iface.path) as dev:
            end = time.monotonic() + seconds
            n = 0
            while time.monotonic() < end:
                r = dev.read_input(timeout_ms=300)
                if not r:
                    continue
                n += 1
                t = time.strftime("%H:%M:%S")
                print(f"    [{t}] len={len(r)}: {r.hex()}")
            if not n:
                print("    (无报文)")
    except hw.HidError as e:
        print(f"    打开失败：{e}")


def main():
    rapoo7 = find(0x24AE, usage_page=0xFF00, usage=0x0002)
    rapoo32 = find(0x24AE, usage_page=0xFF00, usage=0x000E)
    aula = find(0x3554, usage_page=0xFF02, usage=0x0002)

    if rapoo7:
        capture_timed(rapoo7[0], 30)
    if rapoo32:
        probe_ids(rapoo32[0])
    if rapoo7:
        probe_ids(rapoo7[0])
    if aula:
        probe_ids(aula[0])


if __name__ == "__main__":
    main()
