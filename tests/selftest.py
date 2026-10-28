# -*- coding: utf-8 -*-
"""本地修复的回归自检（不需要真实设备）。

    python tests/selftest.py

覆盖四处改动：
  1. 托盘离线图标不再全透明
  2. HID++ getFeature 的 featureIndex 取第 4 字节
  3. HID++ 0x1001 电压按大端解析
  4. 同厂多接口按 output_len / 产品名打分选择
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import battery as bt
import hid_win as hw
import win_icon

fails = []


def check(name, cond, extra=""):
    print(("  ok    " if cond else "  FAIL  ") + name + (("   " + extra) if extra else ""))
    if not cond:
        fails.append(name)


def opaque(px):
    return sum(1 for i in range(3, len(px), 4) if px[i] > 8)


print("[1] 托盘图标")
for text in ("85", "100", "--"):
    n = opaque(win_icon.render_rgba(text, 32, (255, 255, 255)))
    check(f"{text!r} 有可见像素", n > 0, f"opaque={n}")
n = opaque(win_icon.render_rgba("@", 32, (255, 255, 255)))
check("未知字符走兜底字形", n > 0, f"opaque={n}")

print("[2] HID++ featureIndex")
get_feature_reply = bytes([0x11, 0xFF, 0x00, 0x01, 0x07, 0x02, 0x03] + [0] * 13)
bt._hidpp_call = lambda *a, **k: get_feature_reply
idx = bt._hidpp_feature_index(None, 0x11, 0xFF, 0x1004)
check("featureIndex 取 byte4（不是版本号 byte6）", idx == 0x07, f"got={idx}")

print("[3] HID++ 0x1001 电压大端")
voltage_reply = bytes([0x11, 0xFF, 0x05, 0x01, 0x0F, 0x51, 0x00] + [0] * 13)


class _Iface:
    vid = 0x046D
    output_len = 20


bt._hidpp_feature_index = lambda dev, rid, index, fid: 5 if fid == 0x1001 else None
bt._hidpp_call = lambda *a, **k: voltage_reply
res = bt._logitech_probe_index(None, _Iface(), 0x11, 0xFF)
mv = getattr(res, "voltage_mv", None)
check("0x0F51 -> 3921 mV", mv == 3921, f"got={mv}")

print("[4] 接口打分选择")


def mk(path, out_len, product, page=0xFF05, vid=0x373B):
    return hw.HidInterface(
        path=path, vid=vid, pid=0x1216, version=0, usage_page=page, usage=2,
        input_len=64, output_len=out_len, feature_len=0, product=product,
        manufacturer="", serial="",
    )


cands = [mk("a", 0, "ATK Keyboard"), mk("b", 64, "ATK Mouse")]
pick = hw.find_interface(0x373B, usage_page=0xFF05, output_len=64, interfaces=cands)
check("优先 64 字节可写接口", pick is not None and pick.path == "b",
      f"got={getattr(pick, 'path', None)}")
check("usage page 不匹配返回 None",
      hw.find_interface(0x373B, usage_page=0xFF02, interfaces=cands) is None)
check("没有候选返回 None",
      hw.find_interface(0x1234, usage_page=0xFF05, interfaces=cands) is None)
pick2 = hw.find_interface(0x373B, usage_page=0xFF05, product_hint="keyboard",
                          interfaces=cands)
check("产品名提示生效", pick2 is not None and pick2.path == "a",
      f"got={getattr(pick2, 'path', None)}")

print()
if fails:
    print(f"失败 {len(fails)} 项：{fails}")
    sys.exit(1)
print("全部通过")
