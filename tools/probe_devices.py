# -*- coding: utf-8 -*-
"""tools/probe_devices.py —— 针对用户两台设备的定向抓包与协议试探。

只读，不改任何设备设置。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import hid_win as hw
import battery as bt


def find(vid, usage_page=None, usage=None, input_len=None):
    out = []
    for d in hw.enumerate_hid():
        if d.vid != vid:
            continue
        if usage_page is not None and d.usage_page != usage_page:
            continue
        if usage is not None and d.usage != usage:
            continue
        if input_len is not None and d.input_len != input_len:
            continue
        out.append(d)
    return out


def listen_unique(iface, seconds, top=12):
    print(f"\n=== listen {iface.vid_pid} usage={iface.describe_usage()} "
          f"in={iface.input_len} out={iface.output_len} ({seconds}s) ===")
    try:
        with hw.HidDevice(iface.path) as dev:
            seen = {}
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                r = dev.read_input(timeout_ms=250)
                if not r:
                    continue
                h = r.hex()
                seen[h] = seen.get(h, 0) + 1
            for h, c in sorted(seen.items(), key=lambda kv: -kv[1])[:top]:
                n = len(bytes.fromhex(h))
                print(f"   x{c:<3} len={n}: {h}")
            if not seen:
                print("    (无任何 Input Report)")
            return seen
    except hw.HidError as e:
        print(f"    打开失败：{e}")
        return {}


def try_vendor(iface):
    print(f"\n=== vendor protocol 试探 {iface.vid_pid} usage={iface.describe_usage()} ===")
    try:
        res = bt.strategy_vendor_protocol(iface)
    except Exception as e:
        print(f"    exception: {e}")
        return
    if res is None:
        print("    无匹配的内置协议（vid/usage_page 不符）")
        return
    print(f"    ok={res.ok} source={res.source} level={res.level} "
          f"status={res.status} detail={res.detail}")
    if res.raw:
        print(f"    raw={res.raw.hex()}")


def main():
    print("########## RAPOO 24AE:184C (鼠标) ##########")
    for ifc in find(0x24AE):
        if ifc.input_len in (7, 12, 32):
            listen_unique(ifc, 10)

    print("\n\n########## 3554:FA09 (Aula F87 键盘 dongle 候选) ##########")
    aula = find(0x3554)
    print(f"找到 {len(aula)} 个接口：")
    for i, d in enumerate(aula):
        print(f"  [{i}] {d.vid_pid} usage={d.describe_usage()} "
              f"in={d.input_len} out={d.output_len} feat={d.feature_len} "
              f"name={d.product!r}")

    # vendor 接口 0xFF02:0x0002
    vendor = find(0x3554, usage_page=0xFF02, usage=0x0002)
    if vendor:
        try_vendor(vendor[0])
        listen_unique(vendor[0], 12)
    # 键盘接口也听一下（可能有周期性状态包）
    for kb in find(0x3554, usage=0x0006):
        listen_unique(kb, 8)
    # 其它 vendor 接口
    for oth in find(0x3554, usage_page=0xFF04):
        listen_unique(oth, 6)


if __name__ == "__main__":
    main()
