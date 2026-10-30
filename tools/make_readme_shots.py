"""生成 README 用的界面截图，输出到 docs/screenshots/。

用无头 Edge 加载 ui/index.html，注入假后端把数据填上，再截图。
不依赖真实设备，随时可重跑。

用法：
    F:\\Workb\\.venv-2.4G-battery-viewer\\Scripts\\python.exe tools/make_readme_shots.py
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
OUT = ROOT / "docs" / "screenshots"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

MOCK = r"""
<script>
/* ===== README 截图注入：假后端 ===== */
window.pywebview = { api: {
  initial_state: async () => ({
    auto: false, interval: 60,
    device_bg: {},
    device_glass: { rapoo: true, aula: true },
    ui_dark: __DARK__,
    interval_choices: [[30, '30 秒'], [60, '1 分钟'], [120, '2 分钟'], [300, '5 分钟']],
    autostart: true,
    ui_bg: { mode: 'image', value: '_bg.png', accent: '#2c62ba', glass: true, theme_auto: true },
    tray_running: true
  }),
  refresh: async () => ({
    readings: [
      { level: 76, subtitle: '2.4G · 已连接', detail: '信号 -52 dBm', extra: '', error: '' },
      { level: 42, subtitle: '2.4G · 已连接', detail: '信号 -61 dBm', extra: '', error: '' }
    ],
    ts: '16:40:12', ok_count: 2
  }),
  tray_status: async () => ({ running: true }),
  choose_device_bg: async () => ({ ok: false }),
  reset_device_bg: async () => ({ ok: true }),
  set_device_glass: async () => ({ ok: true }),
  set_ui_dark: async () => ({ ok: true }),
  toggle_tray: async () => ({ ok: true }),
  set_auto: async () => ({ ok: true }),
  set_interval: async () => ({ ok: true }),
  set_autostart: async () => ({ ok: true }),
  set_bg: async () => ({ ok: true })
}};
setTimeout(() => window.dispatchEvent(new Event('pywebviewready')), 60);
</script>
"""

# 各场景要做的交互（截图前执行）
ACTIONS = {
    "home-light": "",
    "home-dark": "",
    "device-menu": """
      (async () => {
        await new Promise(r => setTimeout(r, 1400));
        const c = document.querySelector('#homeGrid .card');
        c.dispatchEvent(new MouseEvent('contextmenu', {
          bubbles: true, clientX: 300, clientY: 250
        }));
      })();
    """,
    "detail": """
      (async () => {
        await new Promise(r => setTimeout(r, 1400));
        document.querySelector('#homeGrid .card').click();
      })();
    """,
}

SCENES = [
    ("home-light", False),
    ("home-dark", True),
    ("device-menu", False),
    ("detail", False),
]


def build(dark: bool, actions: str, name: str) -> Path:
    html = (UI / "index.html").read_text(encoding="utf-8")
    mock = MOCK.replace("__DARK__", "true" if dark else "false")
    act = f"<script>{actions}</script>" if actions.strip() else ""
    page = UI / f"_shot_{name}.html"
    page.write_text(html.replace("</body>", mock + act + "</body>"), encoding="utf-8")
    return page


def shot(page: Path, dst: Path, size: str = "1080,820") -> None:
    subprocess.run(
        [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--window-size={size}",
         "--virtual-time-budget=9000", f"--screenshot={dst}", page.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )


def main() -> int:
    if not Path(EDGE).exists():
        print(f"找不到 Edge：{EDGE}")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    bg = UI / "_bg.png"
    shutil.copy(ROOT / "tools" / "_bg.png", bg)

    try:
        for name, dark in SCENES:
            page = build(dark, ACTIONS[name], name)
            dst = OUT / f"{name}.png"
            shot(page, dst)
            size_kb = dst.stat().st_size / 1024 if dst.exists() else 0
            print(f"{dst.relative_to(ROOT)}  {size_kb:.0f} KB")
            page.unlink(missing_ok=True)
    finally:
        bg.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
