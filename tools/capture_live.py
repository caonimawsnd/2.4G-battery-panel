# -*- coding: utf-8 -*-
"""tools/capture_live.py —— 多线程同时监听两台设备所有接口的 Input Report。

用法: python tools/capture_live.py [秒数，默认75]
请在监听期间活动鼠标和键盘！
"""
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import hid_win as hw

LOCK = threading.Lock()
TARGET_VIDS = {0x24AE: "Rapoo鼠标", 0x3554: "Aula键盘dongle"}


def worker(d, seconds):
    tag = f"{TARGET_VIDS.get(d.vid, d.vid_pid)} {d.describe_usage()} in={d.input_len}"
    seen = {}
    try:
        with hw.HidDevice(d.path) as dev:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                r = dev.read_input(timeout_ms=300)
                if not r:
                    continue
                h = r.hex()
                seen.setdefault(h, [0, time.strftime("%H:%M:%S")])
                seen[h][0] += 1
    except hw.HidError as e:
        with LOCK:
            print(f"[{tag}] 打开失败: {e}", flush=True)
        return
    with LOCK:
        if seen:
            for h, (cnt, first) in sorted(seen.items(), key=lambda kv: -kv[1][0])[:6]:
                n = len(bytes.fromhex(h))
                print(f"[{tag}] x{cnt} 首次{first} len={n}: {h}", flush=True)
        else:
            print(f"[{tag}] (无报文)", flush=True)


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 75
    ifaces = [d for d in hw.enumerate_hid() if d.vid in TARGET_VIDS and d.input_len]
    print(f"监听 {len(ifaces)} 个接口，{seconds:.0f} 秒 —— 请活动鼠标、敲键盘！", flush=True)
    t0 = time.strftime("%H:%M:%S")
    threads = [threading.Thread(target=worker, args=(d, seconds), daemon=True)
               for d in ifaces]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"完成（{t0} -> {time.strftime('%H:%M:%S')}）", flush=True)


if __name__ == "__main__":
    main()
