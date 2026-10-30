# -*- coding: utf-8 -*-
"""build.py —— 把程序打包成 exe

    ..\\..\\.venv-2.4G-battery-viewer\\Scripts\\python.exe build.py

产物：dist/设备电量.exe + dist/_internal/（目录模式）
窗口程序，双击打开面板；带 --tray 参数则常驻托盘。
用 --onedir 而不是 --onefile：onefile 每次启动都要把 22MB 解压到临时目录
再被杀软全量扫描，启动要好几秒；onedir 免解压，启动快数倍。

虚拟环境放在项目外的 F:\\Workb\\.venv-2.4G-battery-viewer（110MB），
这样项目文件夹只有 53MB，拷给别人时不会带上开发环境。
需要重建环境时：
    python -m venv F:\\Workb\\.venv-2.4G-battery-viewer
    F:\\Workb\\.venv-2.4G-battery-viewer\\Scripts\\python -m pip install pyinstaller pywebview pillow pythonnet clr_loader
"""

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "设备电量"
# 中间产物放到系统临时目录，不占项目体积（每次 --clean 都会重建，留着也没用）
WORK = os.path.join(tempfile.gettempdir(), "pyinstaller-" + NAME)

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
    path = os.path.join(WORK, "version_info.txt")
    os.makedirs(WORK, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(VERSION_INFO)
    return path


def main() -> int:
    os.chdir(ROOT)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller，请先执行：")
        print("  python -m venv F:\\Workb\\.venv-2.4G-battery-viewer")
        print("  F:\\Workb\\.venv-2.4G-battery-viewer\\Scripts\\python -m pip install "
              "pyinstaller pywebview pillow pythonnet clr_loader")
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
        "--onedir", "--noconsole",
        "--name", NAME,
        "--icon", ico,
        "--version-file", version_file,
        "--add-data", f"{ico};.",
        "--add-data", os.path.join(ROOT, "ui") + ";ui",
        # pywebview（WebView2 网页界面）：整包收集 .NET 互操作运行时
        "--collect-all", "webview",
        "--collect-all", "clr_loader",
        "--collect-all", "pythonnet",
        "--hidden-import", "webview.platforms.winforms",
        "--hidden-import", "webview.platforms.edgechromium",
        # webview.http -> bottle 用到，PyInstaller 分析不到这个条件导入
        "--hidden-import", "unicodedata",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", WORK,
        "--specpath", WORK,
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc_data",
        # 运行时完全用不到，但 PyInstaller 会顺着依赖拖进来
        # numpy 占 27MB（只有 tools/ 下的图像脚本用），scipy/matplotlib 同理
        "--exclude-module", "numpy",
        "--exclude-module", "scipy",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pandas",
        "--exclude-module", "pytest",
        os.path.join(ROOT, "launcher.py"),
    ]
    print("开始打包…")
    subprocess.run(args, check=True)

    # onedir 默认输出 dist/NAME/NAME.exe + _internal/；拍平到 dist/ 根目录，
    # 保持 exe 路径 dist/设备电量.exe 与旧版一致（自启快捷方式不用改）。
    # 顺序很重要：先「改名腾位」再「放入新文件」，最后才尝试删除旧副本。
    # 这样即使删除被拦（杀软/资源管理器占用/批量删除保护），成品也已经是新的，
    # 不会出现「打包显示成功但 exe 还是旧的」。
    import glob
    import shutil
    out_dir = os.path.join(ROOT, "dist", NAME)
    exe = os.path.join(ROOT, "dist", NAME + ".exe")
    if os.path.isdir(out_dir):
        internal_dst = os.path.join(ROOT, "dist", "_internal")
        bak = internal_dst + ".old"
        if os.path.isdir(internal_dst):
            # 上一次的备份先挪个名字，给这次腾位置
            if os.path.exists(bak):
                n = 1
                while os.path.exists(bak + str(n)):
                    n += 1
                os.replace(bak, bak + str(n))
            os.replace(internal_dst, bak)
        for name in os.listdir(out_dir):
            os.replace(os.path.join(out_dir, name),
                       os.path.join(ROOT, "dist", name))
        os.rmdir(out_dir)
        # 成品已就位，这里只是尽量清理旧副本；删不掉也不影响运行
        for p in glob.glob(bak + "*"):
            shutil.rmtree(p, ignore_errors=True)
        if glob.glob(bak + "*"):
            print(f"\n提示：旧副本 {os.path.basename(bak)}* 未能删除，可手动清理。")

    if os.path.exists(exe):
        size = os.path.getsize(exe) / 1024 / 1024
        print(f"\n完成：{exe}  ({size:.1f} MB)")
        return 0
    print("打包结束但没有找到产物，请检查上面的输出")
    return 1


if __name__ == "__main__":
    sys.exit(main())
