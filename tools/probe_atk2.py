# -*- coding: utf-8 -*-
"""tools/probe_atk2.py —— Aula: 0x13 输出 + Feature 回读 组合探测。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import hid_win as hw


def find(vid, usage_page, usage):
    return [d for d in hw.enumerate_hid()
            if d.vid == vid and d.usage_page == usage_page and d.usage == usage]


def atk_frame(op, addr=0, data=b""):
    u8 = [op, 0x00, (addr >> 8) & 0xFF, addr & 0xFF, len(data)] + list(data)
    u8 = (u8 + [0] * 15)[:15]
    return bytes(u8 + [(0x4D - (sum(u8) & 0xFF)) & 0xFF])


def main():
    vendor = find(0x3554, 0xFF02, 0x0002)
    feat = find(0x3554, 0xFF04, 0x0002)
    if not vendor:
        print("no vendor"); return
    v, f = vendor[0], (feat[0] if feat else None)

    def read_feat():
        if not f:
            return None
        try:
            with hw.HidDevice(f.path, write=False) as dev:
                return dev.get_feature_report(0x06, f.feature_len).hex()
        except hw.HidError as e:
            return f"ERR:{e}"

    print("baseline feat0x06:", read_feat())

    frames = {
        "OP04 battery": atk_frame(0x04),
        "OP08 read0":   atk_frame(0x08, 0x0000, None) if False else atk_frame(0x08),
    }
    try:
        with hw.HidDevice(v.path, write=True) as dev:
            out_len = dev.caps.OutputReportByteLength or v.output_len
            for name, fr in frames.items():
                body = bytes([0x13]) + fr + bytes(out_len - 1 - 16)
                for attempt in range(2):
                    try:
                        dev.drain()
                        dev.write_output(body)
                    except hw.HidError as e:
                        print(f"[{name}] 写失败: {e}"); break
                    # 监听 input 1.2s
                    end = time.monotonic() + 1.2
                    while time.monotonic() < end:
                        r = dev.read_input(timeout_ms=150)
                        if r:
                            print(f"[{name}] input: {r.hex()}")
                    val = read_feat()
                    print(f"[{name}] attempt{attempt+1} feat0x06={val}")
                    if val and "ERR" not in str(val) and val != "06000200e600cd83":
                        print("    >>> feature 变化了！")
        # SetFeature 试探
        if f:
            print("\n=== SetFeature on 0xFF04 ===")
            with hw.HidDevice(f.path, write=True) as fdev:
                flen = fdev.caps.FeatureReportByteLength or f.feature_len
                base = read_feat()
                for name, payload in [
                    ("zeros", bytes(flen)),
                    ("atk04", (bytes([0x06]) + atk_frame(0x04)[: flen - 1])),
                    ("atk04pad", (bytes([0x06, 0x04]) + bytes(flen - 2))),
                ]:
                    try:
                        fdev.set_feature_report(payload)
                        time.sleep(0.15)
                        val = read_feat()
                        print(f"[{name}] feat0x06={val} (base={base})")
                    except hw.HidError as e:
                        print(f"[{name}] SetFeature 失败: {e}")
    except hw.HidError as e:
        print(f"打开失败：{e}")


if __name__ == "__main__":
    main()
