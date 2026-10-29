# -*- coding: utf-8 -*-
"""tools/probe_atk.py —— 用正确的 ATK 16 字节帧试探 3554:FA09 的电量。

ATK 帧格式（来自 ClickSync protocol_api_atk.js）：
  [0]=OP [1]=0x00 [2]=ADDR_H [3]=ADDR_L [4]=LEN [5..14]=DATA [15]=CHK
  CHK = (0x4D - sum(bytes0..14)) & 0xFF
电量查询: OP=0x04 -> 04 00 00 00 00 ... 49
回复: ReportID 0x08, 数据 04 xx [Level] ...，Level = frame[5]
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


def atk_frame(op, addr=0, data=b""):
    u8 = [op, 0x00, (addr >> 8) & 0xFF, addr & 0xFF, len(data)] + list(data)
    u8 = (u8 + [0] * 15)[:15]
    chk = (0x4D - (sum(u8) & 0xFF)) & 0xFF
    return bytes(u8 + [chk])


def main():
    ifaces = find(0x3554, 0xFF02, 0x0002)
    if not ifaces:
        print("未找到厂商接口"); return
    ifc = ifaces[0]
    print(f"接口 in={ifc.input_len} out={ifc.output_len}")

    frame = atk_frame(0x04)
    print(f"电量查询帧(16B): {frame.hex()}")

    try:
        with hw.HidDevice(ifc.path, write=True) as dev:
            out_len = dev.caps.OutputReportByteLength or ifc.output_len
            print(f"OutputReportByteLength={out_len}")
            for rid in (0x08, 0x13):
                body = bytes([rid]) + frame + bytes([0] * (out_len - 1 - 16))
                print(f"\n--- 写 Report 0x{rid:02X}（共 {len(body)} 字节）---")
                for attempt in range(3):   # 第一次常被当唤醒
                    try:
                        dev.drain()
                        dev.write_output(body)
                    except hw.HidError as e:
                        print(f"    写失败: {e}")
                        break
                    end = time.monotonic() + 0.6
                    got = False
                    while time.monotonic() < end:
                        r = dev.read_input(timeout_ms=120)
                        if not r:
                            continue
                        got = True
                        print(f"    收到 len={len(r)}: {r.hex()}")
                    if got:
                        break
                    print(f"    (第{attempt+1}次无回复)")
    except hw.HidError as e:
        print(f"打开失败：{e}")


if __name__ == "__main__":
    main()
