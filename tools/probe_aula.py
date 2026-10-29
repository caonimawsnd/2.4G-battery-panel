# -*- coding: utf-8 -*-
"""tools/probe_aula.py —— 针对 3554:FA09 厂商接口 0xFF02:0x0002 (Report ID 0x13) 的主动查询探测。

会向 0x13 写入不同命令字节并监听 Input 回复；同时 dump 0xFF04:0x0002 的 Feature Report。
这是在真实硬件上做协议逆向的常规手段。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import hid_win as hw


def find(vid, usage_page, usage):
    return [d for d in hw.enumerate_hid()
            if d.vid == vid and d.usage_page == usage_page and d.usage == usage]


def dump_feature(iface):
    print(f"\n=== Feature Report dump {iface.vid_pid} usage={iface.describe_usage()} (feat={iface.feature_len}) ===")
    if not iface.feature_len:
        print("    无 Feature Report")
        return
    try:
        with hw.HidDevice(iface.path, write=False) as dev:
            for rid in range(0, 0x21):
                try:
                    data = dev.get_feature_report(rid, iface.feature_len)
                except hw.HidError:
                    continue
                if any(data):
                    print(f"    feat id=0x{rid:02X} len={len(data)}: {data.hex()}")
    except hw.HidError as e:
        print(f"    打开失败：{e}")


def sweep_command(iface, cmds):
    print(f"\n=== 命令字节扫描 0x13 on {iface.vid_pid} usage={iface.describe_usage()} ===")
    try:
        with hw.HidDevice(iface.path, write=True) as dev:
            size = dev.caps.OutputReportByteLength or iface.output_len
            for c in cmds:
                body = [0x13, c] + [0] * (size - 2)
                try:
                    dev.write_output(bytes(body))
                except hw.HidError as e:
                    print(f"    cmd=0x{c:02X} 写失败：{e}")
                    continue
                time.sleep(0.12)
                replies = []
                end = time.monotonic() + 0.5
                while time.monotonic() < end:
                    r = dev.read_input(timeout_ms=120)
                    if r:
                        replies.append(r)
                if replies:
                    print(f"    cmd=0x{c:02X} -> {len(replies)} 条回复:")
                    for r in replies[:3]:
                        print(f"        len={len(r)}: {r.hex()}")
    except hw.HidError as e:
        print(f"    打开失败：{e}")


def capture(iface, seconds):
    print(f"\n=== 监听 Input {iface.vid_pid} usage={iface.describe_usage()} ({seconds}s) ===")
    try:
        with hw.HidDevice(iface.path) as dev:
            end = time.monotonic() + seconds
            seen = {}
            while time.monotonic() < end:
                r = dev.read_input(timeout_ms=300)
                if not r:
                    continue
                seen[r.hex()] = seen.get(r.hex(), 0) + 1
            for h, c in sorted(seen.items(), key=lambda kv: -kv[1])[:10]:
                print(f"    x{c} len={len(bytes.fromhex(h))}: {h}")
            if not seen:
                print("    (无报文)")
    except hw.HidError as e:
        print(f"    打开失败：{e}")


def main():
    aula_vendor = find(0x3554, 0xFF02, 0x0002)
    aula_feat = find(0x3554, 0xFF04, 0x0002)
    if not aula_vendor:
        print("未找到 0xFF02:0x0002 接口")
        return
    ifc = aula_vendor[0]

    if aula_feat:
        dump_feature(aula_feat[0])

    capture(ifc, 12)

    # 常见命令字节：0=空查询, 0x20 族状态, 0x10/0x11 信息, 0x04 类, 0xB0 广播, 0x01/0x02
    cmds = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x10, 0x11, 0x12,
            0x13, 0x14, 0x20, 0x21, 0x22, 0x30, 0x40, 0x41, 0x50, 0x60,
            0xB0, 0xC0, 0xD0, 0xE0, 0xF0]
    sweep_command(ifc, cmds)


if __name__ == "__main__":
    main()
