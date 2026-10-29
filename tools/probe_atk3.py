# -*- coding: utf-8 -*-
"""tools/probe_atk3.py —— Aula 0xFF04 Feature 短帧协议系统探测。

发现：SetFeature([06, op, ...]) 后 GetFeature(0x06) 的 byte1 会回显 op。
本脚本用多个 op 探测响应差异，并连续读取观察动态字节。
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


def main():
    feat = find(0x3554, 0xFF04, 0x0002)
    vendor = find(0x3554, 0xFF02, 0x0002)
    if not feat:
        print("no feat iface"); return
    f = feat[0]
    flen = f.feature_len
    print(f"feat iface len={flen}")

    ops = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x10, 0x11, 0x20, 0xA0]
    with hw.HidDevice(f.path, write=True) as fdev:
        for op in ops:
            payload = bytes([0x06, op] + [0] * (flen - 2))
            try:
                fdev.set_feature_report(payload)
            except hw.HidError as e:
                print(f"op=0x{op:02X}: SetFeature 失败 {e}")
                continue
            time.sleep(0.12)
            reads = []
            for _ in range(3):
                try:
                    reads.append(fdev.get_feature_report(0x06, flen).hex())
                except hw.HidError as e:
                    reads.append(f"ERR:{e}")
                time.sleep(0.06)
            uniq = list(dict.fromkeys(reads))
            print(f"op=0x{op:02X}: " + " | ".join(uniq))

    # 顺带：SetFeature 后监听 0xFF02 input
    if vendor:
        print("\n=== SetFeature(0x04) 后监听 vendor Input 2s ===")
        v = vendor[0]
        try:
            with hw.HidDevice(f.path, write=True) as fdev, \
                 hw.HidDevice(v.path, write=False) as vdev:
                fdev.set_feature_report(bytes([0x06, 0x04] + [0] * (flen - 2)))
                end = time.monotonic() + 2.0
                while time.monotonic() < end:
                    r = vdev.read_input(timeout_ms=200)
                    if r:
                        print(f"    input len={len(r)}: {r.hex()}")
                print("    (监听结束)")
        except hw.HidError as e:
            print(f"    失败：{e}")


if __name__ == "__main__":
    main()
