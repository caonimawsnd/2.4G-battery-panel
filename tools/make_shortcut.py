# -*- coding: utf-8 -*-
"""生成「我的设备电量」快捷方式（指向 pythonw.exe + my_devices.py，不弹黑窗）。

    python tools/make_shortcut.py                 # 项目目录 + 桌面各建一个
    python tools/make_shortcut.py --no-desktop    # 只在项目目录里建

项目目录整体搬家后，重新跑一次即可修好快捷方式的路径。
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tray_common as tc
import win_shell

NAME = "我的设备电量.lnk"
DESC = "2.4G 无线外设电量面板"


def make(folder: str) -> bool:
    path = os.path.join(folder, NAME)
    if os.path.exists(path):
        print(f"  已存在，跳过：{path}")
        return True
    ok = win_shell.create_shortcut(
        path,
        tc.pythonw_path(),
        arguments=f'"{os.path.join(ROOT, "my_devices.py")}"',
        workdir=ROOT,
        description=DESC,
    )
    print(("  已创建 " if ok else "  失败 ") + path)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-desktop", action="store_true", help="不建桌面快捷方式")
    args = ap.parse_args()

    print("pythonw:", tc.pythonw_path())
    ok = make(ROOT)
    if not args.no_desktop:
        ok = make(win_shell.desktop_dir()) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
