"""界面冒烟测试：用假后端把 ui/index.html 跑起来，验证右键菜单 / 毛玻璃 / 背景图 / 图片回退。

用法（虚拟环境在项目外）：
    F:\\Workb\\.venv-2.4G-battery-viewer\\Scripts\\python.exe tools/smoke_test.py
    加 --shot 额外输出浅色/深色截图
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

MOCK = r"""
<script>
/* ===== 冒烟测试注入：假后端 ===== */
window.__calls = [];
const __rec = (n) => (...a) => { window.__calls.push([n, ...a]); return Promise.resolve({ok: true}); };
window.pywebview = { api: {
  initial_state: async () => ({
    auto: false, interval: 60,
    device_bg: {},
    device_glass: { rapoo: true },
    ui_dark: __DARK__,
    interval_choices: [[30, '30 秒'], [60, '1 分钟'], [120, '2 分钟'], [300, '5 分钟']],
    autostart: false,
    ui_bg: { mode: 'image', value: '_bg.png', accent: '#5b6b7f', glass: __BGGLASS__, theme_auto: true },
    tray_running: true
  }),
  refresh: async () => ({
    readings: [
      { level: 76, subtitle: '2.4G · 已连接', detail: '信号 -52 dBm', extra: '', error: '' },
      { level: 42, subtitle: '2.4G · 已连接', detail: '信号 -61 dBm', extra: '', error: '' }
    ],
    ts: '13:49:20', ok_count: 2
  }),
  tray_status: async () => ({ running: true }),
  choose_device_bg: async (key) => ({ ok: true, key: key, path: '_bg.png' }),
  reset_device_bg: __rec('reset_device_bg'),
  set_device_glass: __rec('set_device_glass'),
  set_ui_dark: __rec('set_ui_dark'),
  toggle_tray: __rec('toggle_tray'),
  set_auto: __rec('set_auto'),
  set_interval: __rec('set_interval'),
  set_autostart: __rec('set_autostart'),
  set_bg: __rec('set_bg')
}};
setTimeout(() => window.dispatchEvent(new Event('pywebviewready')), 60);
</script>
"""

PROBE = r"""
<script>
(async () => {
  const out = [];
  const ok = (n, c, e) => out.push((c ? 'PASS ' : 'FAIL ') + n + (e ? ' | ' + e : ''));
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  await wait(1000);

  const foot = document.getElementById('footText').textContent;
  ok('初始化无异常', !/初始化失败/.test(foot), foot.slice(0, 60));

  const cards = [...document.querySelectorAll('#homeGrid .card')];
  ok('卡片数量=2', cards.length === 2, 'n=' + cards.length);
  ok('device_glass.rapoo=true → 卡片0 有 glass', cards[0].classList.contains('glass'));
  ok('卡片1 未单独设置 → 既无 glass 也无 solid',
     !cards[1].classList.contains('glass') && !cards[1].classList.contains('solid'),
     cards[1].className);

  const cs0 = getComputedStyle(cards[0]);
  ok('卡片0 backdrop-filter 生效', /blur/.test(cs0.backdropFilter || cs0.webkitBackdropFilter || ''));
  const cs1 = getComputedStyle(cards[1]);
  ok('卡片1 无 backdrop-filter', !/blur/.test(cs1.backdropFilter || cs1.webkitBackdropFilter || ''));

  const g0 = document.getElementById('glyph0');
  ok('产品图已加载', !!g0.querySelector('img'));
  S.devBg.rapoo = '_bg.png';
  applyDeviceCards();
  await wait(150);
  const blurEl = g0.querySelector('.bg-blur');
  const fullEl = g0.querySelector('.bg-full');
  ok('自定义背景图 → 插入模糊层 + 完整层', !!blurEl && !!fullEl);
  ok('完整层用 contain（不裁切）',
     fullEl && getComputedStyle(fullEl).backgroundSize === 'contain',
     fullEl ? getComputedStyle(fullEl).backgroundSize : 'null');
  ok('模糊层用 cover（铺满延展）',
     blurEl && getComputedStyle(blurEl).backgroundSize === 'cover',
     blurEl ? getComputedStyle(blurEl).backgroundSize : 'null');
  ok('模糊层真的模糊了', blurEl && /blur/.test(getComputedStyle(blurEl).filter),
     blurEl ? getComputedStyle(blurEl).filter : 'null');
  ok('背景层在产品图之下',
     !!g0.querySelector('img') && !!fullEl &&
     (fullEl.compareDocumentPosition(g0.querySelector('img')) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0);
  delete S.devBg.rapoo;
  applyDeviceCards();
  await wait(80);
  ok('清除后背景层被移除',
     !g0.querySelector('.bg-blur') && !g0.querySelector('.bg-full') &&
     !g0.classList.contains('has-bg'));

  // 内置素材缺失时（用不存在的 key 模拟）应回退到线稿
  setGlyph(g0, 'nope');
  await wait(300);
  ok('产品图加载失败 → 回退线稿（不留空框）', g0.querySelector('svg') !== null, 'len=' + g0.innerHTML.length);
  applyDeviceCards();

  // ---- 右键卡片1：毛玻璃开关 ----
  cards[1].dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 400, clientY: 300 }));
  await wait(60);
  const menu = document.getElementById('devMenu');
  ok('右键弹出菜单', menu.style.display === 'block');
  ok('菜单 3 项 + 分隔线', menu.querySelectorAll('.ctx-item').length === 3 && !!menu.querySelector('.ctx-sep'));
  ok('菜单文案已改为背景图', /自定义设备背景图/.test(document.getElementById('devPick').textContent));
  const cb = document.getElementById('devGlass');
  ok('卡片1 勾选态=false（全局玻璃关）', cb.checked === false);

  cb.checked = true; cb.dispatchEvent(new Event('change'));
  await wait(120);
  ok('勾选 → 卡片1 加 glass', cards[1].classList.contains('glass') && !cards[1].classList.contains('solid'));
  const c1 = window.__calls.filter(c => c[0] === 'set_device_glass').pop();
  ok('回写 set_device_glass(aula,true)', !!c1 && c1[1] === 'aula' && c1[2] === true,
     c1 ? JSON.stringify(c1) : 'no call');

  cb.checked = false; cb.dispatchEvent(new Event('change'));
  await wait(120);
  ok('取消 → 卡片1 变 solid（显式关闭）',
     cards[1].classList.contains('solid') && !cards[1].classList.contains('glass'));

  // ---- 全局毛玻璃打开后，显式关闭的卡片仍然不透明 ----
  S.bg.glass = true;
  applyBg(S.bg);
  await wait(120);
  ok('全局玻璃已开启', document.body.classList.contains('glass-on'));
  ok('显式关闭的卡片1 仍是 solid', cards[1].classList.contains('solid') && !cards[1].classList.contains('glass'));
  const c1cs = getComputedStyle(cards[1]);
  ok('卡片1 无 backdrop-filter（压过全局）', !/blur/.test(c1cs.backdropFilter || c1cs.webkitBackdropFilter || ''),
     c1cs.backdropFilter);

  // 未单独设置的卡片应跟随全局
  delete S.devGlass.aula;
  applyDeviceGlass();
  await wait(80);
  ok('清除显式设置后卡片1 跟随全局（无 solid）', !cards[1].classList.contains('solid'));
  const c1cs2 = getComputedStyle(cards[1]);
  ok('跟随全局后卡片1 有 backdrop-filter', /blur/.test(c1cs2.backdropFilter || c1cs2.webkitBackdropFilter || ''),
     c1cs2.backdropFilter);

  // ---- 详情页继承 ----
  cards[0].click();
  await wait(200);
  const panel = document.querySelector('#viewDetail .panel');
  ok('详情页 panel 继承 glass', !!panel && panel.classList.contains('glass'), panel ? panel.className : '');
  ok('详情页图片有内容', document.getElementById('dGlyph').innerHTML.trim().length > 0);

  document.getElementById('viewDetail').style.display = 'none';
  document.getElementById('viewHome').style.display = 'block';
  cards[0].dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 400, clientY: 300 }));
  await wait(60);
  ok('卡片0 菜单勾选态=true', document.getElementById('devGlass').checked === true);
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await wait(60);
  ok('ESC 关闭菜单', menu.style.display === 'none');

  const pre = document.createElement('pre');
  pre.id = 'RESULT'; pre.textContent = out.join('\n');
  document.body.appendChild(pre);
})();
</script>
"""


def build(dark: bool, bg_glass: bool = False) -> Path:
    html = (UI / "index.html").read_text(encoding="utf-8")
    mock = (MOCK
            .replace("__DARK__", "true" if dark else "false")
            .replace("__BGGLASS__", "true" if bg_glass else "false"))
    name = "_smoke_dark.html" if dark else "_smoke.html"
    path = UI / name
    path.write_text(html.replace("</body>", mock + PROBE + "</body>"), encoding="utf-8")
    return path


def run_dom(page: Path) -> str:
    out = ROOT / "tools" / "_dom.html"
    with open(out, "w", encoding="utf-8") as fh:
        subprocess.run(
            [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=1", "--window-size=1100,900",
             "--virtual-time-budget=8000", "--dump-dom", page.as_uri()],
            stdout=fh, stderr=subprocess.DEVNULL, check=False,
        )
    s = out.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'<pre id="RESULT">(.*?)</pre>', s, re.S)
    return m.group(1) if m else f"NO RESULT (len={len(s)})"


def shot(page: Path, dst: Path, size: str = "1080,800") -> None:
    """按 1:1 像素输出，size 就是 CSS 视口。"""
    subprocess.run(
        [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--window-size={size}",
         "--virtual-time-budget=8000", f"--screenshot={dst}", page.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )


def main() -> int:
    bg = UI / "_bg.png"
    bg.write_bytes((ROOT / "tools" / "_bg.png").read_bytes())

    light = build(False)
    result = run_dom(light)
    print(result)

    if "--shot" in sys.argv:
        dark = build(True)
        run_dom(dark)
        shot(light, ROOT / "tools" / "_v_light.png")
        shot(dark, ROOT / "tools" / "_v_dark.png")
        print("\n截图: tools/_v_light.png  tools/_v_dark.png")

    # 收尾：测试产物不留在 ui/ 里
    for p in [light, UI / "_smoke_dark.html", bg, ROOT / "tools" / "_dom.html"]:
        p.unlink(missing_ok=True)

    fails = [ln for ln in result.splitlines() if ln.startswith("FAIL")]
    print(f"\n{len(result.splitlines()) - len(fails)}/{len(result.splitlines())} 通过")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
