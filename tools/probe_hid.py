# -*- coding: utf-8 -*-
"""tools/probe_hid.py —— HID 只读探测（枚举 / 读 Feature Report / 监听 Input Report）

    python tools/probe_hid.py                 # 枚举所有接口
    python tools/probe_hid.py --vid 24AE      # 只看某个厂商
    python tools/probe_hid.py --vid 24AE --feature   # 试读 Feature Report 0x00-0x20
    python tools/probe_hid.py --vid 24AE --listen 6  # 监听 6 秒 Input Report

只做读操作（HidD_GetFeature / ReadFile），不发任何 SetFeature / WriteFile，
所以不会改动鼠标的 DPI、灯效、回报率等设置。
"""

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import hid_win as hw


def dump(vid_filter=None):
    items = hw.enumerate_hid()
    if vid_filter:
        items = [d for d in items if d.vid == vid_filter]
    print(f"共 {len(items)} 个接口\n")
    for i, d in enumerate(items):
        print(f"[{i}] {d.vid_pid}  usage={d.describe_usage()}  "
              f"in={d.input_len} out={d.output_len} feat={d.feature_len}")
        print(f"    产品名: {d.product or '(空)'}   厂商: {d.manufacturer or '(空)'}")
        print(f"    序列号: {(d.serial or '(空)')[:40]}")
        print(f"    feature值域数={d.num_feature_value_caps} "
              f"input值域数={d.num_input_value_caps} 错误={d.error or '无'}")
        print(f"    path: ...{d.path[-70:]}")
    return items


def try_feature(items, max_id=0x20):
    print("\n=== 试读 Feature Report（只读，不会改设置）===")
    for d in items:
        if not d.feature_len:
            print(f"- {d.vid_pid} {d.describe_usage()} 没有 Feature Report，跳过")
            continue
        print(f"\n- {d.vid_pid} {d.describe_usage()} (feat={d.feature_len})")
        try:
            with hw.HidDevice(d.path) as dev:
                hits = 0
                for rid in range(0, max_id + 1):
                    try:
                        data = dev.get_feature_report(rid, d.feature_len)
                    except hw.HidError:
                        continue
                    body = data[1:] if data and data[0] == rid else data
                    if any(body):
                        hits += 1
                        hexs = " ".join(f"{b:02X}" for b in data[:24])
                        print(f"    id=0x{rid:02X} len={len(data)}: {hexs}")
                if not hits:
                    print("    0x00-0x%02X 全部为空或无响应" % max_id)
        except hw.HidError as e:
            print(f"    打开失败：{e}")


def listen(items, seconds=6.0):
    print(f"\n=== 监听 Input Report {seconds} 秒（动一下鼠标/按按键更容易有数据）===")
    for d in items:
        if not d.input_len:
            print(f"- {d.vid_pid} {d.describe_usage()} 没有 Input Report，跳过")
            continue
        print(f"\n- {d.vid_pid} {d.describe_usage()} (in={d.input_len})")
        try:
            with hw.HidDevice(d.path) as dev:
                end = time.monotonic() + seconds
                seen = {}
                while time.monotonic() < end:
                    r = dev.read_input(timeout_ms=200)
                    if not r:
                        continue
                    key = r[:8].hex()
                    seen[key] = seen.get(key, 0) + 1
                    if seen[key] <= 3:
                        hexs = " ".join(f"{b:02X}" for b in r[:24])
                        print(f"    len={len(r)}: {hexs}")
                if not seen:
                    print("    没有收到任何报文")
                else:
                    print(f"    共 {sum(seen.values())} 条，{len(seen)} 种")
        except hw.HidError as e:
            print(f"    打开失败：{e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vid", help="只看某个厂商 ID，十六进制，如 24AE")
    ap.add_argument("--feature", action="store_true", help="试读 Feature Report")
    ap.add_argument("--listen", type=float, default=0, help="监听 Input Report 的秒数")
    args = ap.parse_args()

    vid = int(args.vid, 16) if args.vid else None
    items = dump(vid)
    if args.feature:
        try_feature(items)
    if args.listen:
        listen(items, args.listen)


if __name__ == "__main__":
    main()
