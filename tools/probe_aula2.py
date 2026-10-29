# -*- coding: utf-8 -*-
"""tools/probe_aula2.py —— 发送 0x13 命令后回读 Feature 0x06，观察是否变化。"""
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
    vendor = find(0x3554, 0xFF02, 0x0002)
    feat = find(0x3554, 0xFF04, 0x0002)
    if not vendor:
        print("no vendor iface"); return
    v = vendor[0]
    f = feat[0] if feat else None

    def read_feat():
        if not f:
            return None
        try:
            with hw.HidDevice(f.path, write=False) as dev:
                return dev.get_feature_report(0x06, f.feature_len).hex()
        except hw.HidError as e:
            return f"ERR {e}"

    print("baseline feat0x06:", read_feat())
    cmds = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x10, 0x11, 0x12, 0x13,
            0x14, 0x20, 0x21, 0x22, 0x30, 0x40, 0x50, 0x60, 0xB0, 0xC0, 0xFF]
    try:
        with hw.HidDevice(v.path, write=True) as dev:
            size = dev.caps.OutputReportByteLength or v.output_len
            for c in cmds:
                # 尝试两种常见命令结构
                for payload in ([c], [0x20, c], [c, 0x00]):
                    body = [0x13] + payload + [0] * (size - 1 - len(payload))
                    try:
                        dev.write_output(bytes(body))
                    except hw.HidError:
                        continue
                    time.sleep(0.10)
                val = read_feat()
                print(f"  after cmd=0x{c:02X}: feat0x06={val}")
                time.sleep(0.05)
    except hw.HidError as e:
        print(f"打开失败：{e}")


if __name__ == "__main__":
    main()
