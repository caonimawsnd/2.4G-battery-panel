# -*- coding: utf-8 -*-
"""生成「我的设备电量」快捷方式。

    python tools/make_shortcut.py                 # 项目目录 + 桌面各建一个
    python tools/make_shortcut.py --no-desktop    # 只在项目目录里建

优先指向打包好的 dist/设备电量.exe；没打包过则退回 pythonw + my_devices.py。
项目整体搬家后重新跑一次即可修好快捷方式的路径。
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
EXE = os.path.join(ROOT, "dist", "设备电量.exe")


def launcher():
    """返回 (目标程序, 参数, 说明)。"""
    if os.path.exists(EXE):
        return EXE, "", "打包版 exe"
    return tc.pythonw_path(), f'"{os.path.join(ROOT, "my_devices.py")}"', "脚本版"


def make(folder: str) -> bool:
    path = os.path.join(folder, NAME)
    if os.path.exists(path):
        os.remove(path)          # 覆盖旧的（可能还指向 pythonw）
    target, arguments, kind = launcher()
    ok = win_shell.create_shortcut(
        path, target, arguments=arguments, workdir=ROOT, description=DESC)
    print(("  已创建 " if ok else "  失败 ") + f"{path}  ->  {kind}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-desktop", action="store_true", help="不建桌面快捷方式")
    args = ap.parse_args()

    target, _, kind = launcher()
    print(f"启动目标：{target}  （{kind}）")
    ok = make(ROOT)
    if not args.no_desktop:
        ok = make(win_shell.desktop_dir()) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
