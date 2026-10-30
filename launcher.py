# -*- coding: utf-8 -*-
"""launcher.py —— 打包成 exe 时的统一入口

同一个 exe 承担两个角色：

    设备电量.exe            打开 Fluent 面板（WebView2 网页界面）
    设备电量.exe --tray     常驻托盘（开机自启用的就是这个）

脚本模式下这两个角色分别由 ui_fluent.py / tray_app.py 承担，行为不变。
"""

import os
import sys


def _fix_streams() -> None:
    """--noconsole 打包后 sys.stdout/stderr 是 None，任何 print() 都会抛异常。"""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass
    if getattr(sys, "stdin", None) is None:
        try:
            sys.stdin = open(os.devnull, "r", encoding="utf-8")
        except OSError:
            pass


# 这几个参数属于托盘程序（tray_app.py），其余都给面板
TRAY_FLAGS = ("--tray", "--quit", "--status")


def main():
    _fix_streams()

    argv = sys.argv[1:]
    want_tray = any(a in TRAY_FLAGS for a in argv)
    sys.argv = [sys.argv[0]] + [a for a in argv if a != "--tray"]

    if want_tray:
        import tray_app
        return tray_app.main()

    import ui_fluent
    return ui_fluent.main()


if __name__ == "__main__":
    sys.exit(main() or 0)
