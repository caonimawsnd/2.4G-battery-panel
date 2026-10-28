# -*- coding: utf-8 -*-
"""build.py —— 把程序打包成单文件 exe

    python build.py

产物：dist/设备电量.exe（窗口程序，双击打开面板；带 --tray 参数则常驻托盘）

需要 PyInstaller：
    python -m venv .venv
    .venv\\Scripts\\python -m pip install pyinstaller
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "设备电量"

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 0, 0, 0),
    prodvers=(1, 0, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('CompanyName', ''),
        StringStruct('FileDescription', '2.4G 无线外设电量面板'),
        StringStruct('FileVersion', '1.0.0.0'),
        StringStruct('InternalName', 'DeviceBattery'),
        StringStruct('LegalCopyright', '基于 yszyszysz233/2.4G-battery-viewer 修改'),
        StringStruct('OriginalFilename', '设备电量.exe'),
        StringStruct('ProductName', '设备电量'),
        StringStruct('ProductVersion', '1.0.0.0')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""


def write_version_file() -> str:
    path = os.path.join(ROOT, "build", "version_info.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(VERSION_INFO)
    return path


def main() -> int:
    os.chdir(ROOT)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller，请先执行：")
        print("  python -m venv .venv")
        print("  .venv\\Scripts\\python -m pip install pyinstaller")
        return 1

    ico = os.path.join(ROOT, "app.ico")
    if not os.path.exists(ico):
        print("app.ico 不存在，先生成图标…")
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_icon.py")],
                       check=True)

    version_file = write_version_file()

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--noconsole",
        "--name", NAME,
        "--icon", ico,
        "--version-file", version_file,
        "--add-data", f"{ico};.",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc_data",
        os.path.join(ROOT, "launcher.py"),
    ]
    print("开始打包…")
    subprocess.run(args, check=True)

    exe = os.path.join(ROOT, "dist", NAME + ".exe")
    if os.path.exists(exe):
        size = os.path.getsize(exe) / 1024 / 1024
        print(f"\n完成：{exe}  ({size:.1f} MB)")
        return 0
    print("打包结束但没有找到产物，请检查上面的输出")
    return 1


if __name__ == "__main__":
    sys.exit(main())
