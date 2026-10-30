# -*- coding: utf-8 -*-
"""ui_fluent.py —— Fluent 风格面板（pywebview + Edge WebView2）

用系统自带的 Edge WebView2 渲染一份网页界面（ui/index.html），
Python 侧通过 js_api 提供数据（读电量、配置、托盘控制、背景设置）。

用法：
    python ui_fluent.py            打开面板

窗口标题保持 tray_common.UI_TITLE 不变：托盘靠 FindWindowW 按标题
找到本窗口（隐藏的窗口也能找到，SW_RESTORE 即可召回）。
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback

import webview

import tray_common as tc
import my_devices as md
import win_link


def _hsl_hex(h: float, s: float, l: float) -> str:
    """HSL(0-360, 0-1, 0-1) → '#rrggbb'。"""
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h / 360, l, s)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _ui_path() -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "ui", "index.html")


def _reading_dict(r: md.Reading) -> dict:
    return {
        "title": r.title,
        "subtitle": r.subtitle,
        "level": r.level,
        "status": r.status,
        "detail": r.detail,
        "error": r.error,
        "extra": r.extra,
        "ok": r.ok,
        "dpi": r.dpi,
    }


class Api:
    """暴露给网页 JS 的接口（window.pywebview.api.*）。"""

    def __init__(self):
        self._lock = threading.Lock()      # 电量读取是串行硬件操作，防并发

    # ---- 状态 ----
    def initial_state(self) -> dict:
        cfg = tc.load_config()
        return {
            "title": tc.UI_TITLE,
            "interval": int(cfg["interval"]),
            "interval_choices": [[sec, name] for sec, name in tc.INTERVAL_CHOICES],
            "autostart": tc.is_autostart_enabled(),
            "tray_running": tc.is_tray_running(),
            "auto": True,
            "ui_bg": cfg.get("ui_bg"),
            "ui_dark": bool(cfg.get("ui_dark")),
            "device_bg": dict(cfg.get("device_bg") or {}),
            "device_glass": dict(cfg.get("device_glass") or {}),
        }

    # ---- 读电量（雷柏广播要等 ~10 秒，调用方自负耐心）----
    def refresh(self) -> dict:
        if not self._lock.acquire(blocking=False):
            return {"busy": True}
        try:
            readings = md.read_all()
        except Exception:
            traceback.print_exc()
            readings = [md.Reading("雷柏鼠标", "", error="读取异常"),
                        md.Reading("狼蛛 F87 键盘", "", error="读取异常")]
        finally:
            self._lock.release()
        ok = sum(1 for r in readings if r.ok)
        return {
            "readings": [_reading_dict(r) for r in readings],
            "ts": time.strftime("%H:%M:%S"),
            "ok_count": ok,
        }

    # ---- 系统级鼠标设置（移植自雷柏官方 AHUB 驱动的实现）----
    def get_mouse_sys(self) -> dict:
        import win_mouse
        return win_mouse.get_mouse_sys()

    def set_pointer_speed(self, value: int) -> dict:
        import win_mouse
        ok = win_mouse.set_pointer_speed(int(value))
        return {"ok": ok, "pointer_speed": win_mouse.get_pointer_speed(),
                "message": "指针速度已更新" if ok else "指针速度必须在 1-20 之间"}

    def set_wheel_lines(self, value: int) -> dict:
        import win_mouse
        ok = win_mouse.set_wheel_scroll_lines(int(value))
        return {"ok": ok, "wheel_lines": win_mouse.get_wheel_scroll_lines(),
                "message": "滚轮行数已更新" if ok else "滚轮行数必须在 1-100 之间（-1 为整页）"}

    def measure_polling(self) -> dict:
        """实测回报率：测量期间请晃动鼠标。"""
        import win_mouse
        if self._lock.acquire(blocking=False):
            try:
                return win_mouse.measure_polling_rate(seconds=2.0)
            finally:
                self._lock.release()
        return {"hz": 0, "samples": 0, "moved": False, "error": "正在读取电量，请稍后再试"}

    # ---- 配置 ----
    def set_interval(self, seconds: int) -> dict:
        seconds = max(30, int(seconds))
        cfg = tc.load_config()
        cfg["interval"] = seconds
        tc.save_config(cfg)
        tc.post_to_tray(tc.MSG_RELOAD)     # 让托盘立刻换间隔
        return {"ok": True, "interval": seconds}

    def set_autostart(self, on: bool) -> dict:
        on = bool(on)
        ok = tc.set_autostart(on)
        cfg = tc.load_config()
        cfg["autostart"] = on
        tc.save_config(cfg)
        tc.post_to_tray(tc.MSG_RELOAD)
        if on and not ok:
            return {"ok": False, "message": "开机自启设置失败：无法创建启动文件夹快捷方式"}
        if on:
            return {"ok": True, "message": "已加入开机自启（任务管理器 →「启动」标签里能看到 电量托盘）"}
        return {"ok": True, "message": "已取消开机自启"}

    # ---- 外观（背景 / 暗色 / 主题色 / 毛玻璃）----
    def set_ui_bg(self, cfg: dict) -> dict:
        """cfg = {mode: none|color|image, value, accent, glass, theme_auto}"""
        if not isinstance(cfg, dict) or cfg.get("mode") not in ("none", "color", "image"):
            return {"ok": False}
        clean = {
            "mode": cfg["mode"],
            "value": str(cfg.get("value") or ""),
            "path": str(cfg.get("path") or ""),
            "accent": str(cfg.get("accent") or ""),
            "glass": bool(cfg.get("glass")),
            "theme_auto": bool(cfg.get("theme_auto", True)),
        }
        c = tc.load_config()
        c["ui_bg"] = clean
        tc.save_config(c)
        return {"ok": True}

    def set_ui_dark(self, on: bool) -> dict:
        cfg = tc.load_config()
        cfg["ui_dark"] = bool(on)
        tc.save_config(cfg)
        return {"ok": True}

    def extract_theme_color(self, path: str) -> dict:
        """提取背景图的主色调，作为界面主题色。

        统计高饱和像素的色相分布，取权重最高的色相，
        固定一个耐看的饱和度/明度生成强调色。灰图返回空串走默认。
        """
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            img.thumbnail((96, 96))
            buckets: dict[int, float] = {}
            for (r, g, b) in img.getdata():
                rf, gf, bf = r / 255, g / 255, b / 255
                mx, mn = max(rf, gf, bf), min(rf, gf, bf)
                v = mx
                s = (mx - mn) / mx if mx else 0
                if v < 0.22 or s < 0.22:          # 跳过近黑/近白/灰像素
                    continue
                df = mx - mn
                if mx == rf:
                    h = ((gf - bf) / df) % 6
                elif mx == gf:
                    h = (bf - rf) / df + 2
                else:
                    h = (rf - gf) / df + 4
                h = int(h * 60) % 360
                key = h // 15
                buckets[key] = buckets.get(key, 0) + v * (0.3 + 0.7 * s)
            if not buckets:
                return {"ok": True, "accent": ""}
            best = max(buckets.items(), key=lambda kv: kv[1])[0]
            hue = best * 15 + 7
            return {"ok": True, "accent": _hsl_hex(hue, 0.62, 0.45)}
        except Exception:
            traceback.print_exc()
            return {"ok": False, "accent": ""}

    def choose_device_bg(self, key: str) -> dict:
        """右键设备卡 → 自定义设备背景图：选图并按设备持久化。"""
        if key not in ("rapoo", "aula"):
            return {"ok": False, "message": "未知设备"}
        path = self.choose_bg_image()
        if not path:
            return {"ok": False, "cancelled": True}
        cfg = tc.load_config()
        bgs = dict(cfg.get("device_bg") or {})
        bgs[key] = path
        cfg["device_bg"] = bgs
        tc.save_config(cfg)
        return {"ok": True, "key": key, "path": path}

    def reset_device_bg(self, key: str) -> dict:
        if key not in ("rapoo", "aula"):
            return {"ok": False}
        cfg = tc.load_config()
        bgs = dict(cfg.get("device_bg") or {})
        bgs.pop(key, None)
        cfg["device_bg"] = bgs
        tc.save_config(cfg)
        return {"ok": True, "key": key}

    def set_device_glass(self, key: str, on: bool) -> dict:
        """右键设备卡 → 毛玻璃效果：按设备持久化。

        显式记录 True/False —— False 表示「这张卡片强制不透明」，
        可以压过全局背景毛玻璃；键不存在则跟随全局。
        """
        if key not in ("rapoo", "aula"):
            return {"ok": False}
        cfg = tc.load_config()
        glass = dict(cfg.get("device_glass") or {})
        glass[key] = bool(on)
        cfg["device_glass"] = glass
        tc.save_config(cfg)
        return {"ok": True, "key": key, "on": bool(on)}

    def choose_bg_image(self) -> str:
        """弹出文件选择框，返回图片路径（取消返回空串）。"""
        try:
            wnd = webview.windows[0]
            result = wnd.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("图片文件 (*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif)",
                            "所有文件 (*.*)"),
            )
            if result:
                return result[0] if isinstance(result, (list, tuple)) else result
        except Exception:
            traceback.print_exc()
        return ""

    # ---- 托盘 ----
    def tray_status(self) -> dict:
        return {"running": tc.is_tray_running()}

    def toggle_tray(self) -> dict:
        if tc.is_tray_running():
            tc.post_to_tray(tc.MSG_QUIT)
            return {"running": False, "message": "托盘已退出"}
        # start_tray_app 内部会等托盘窗口出现（最多 6 秒），
        # pywebview 的 api 调用跑在独立线程，阻塞在这里不影响界面
        try:
            ok = tc.start_tray_app()
        except Exception:
            traceback.print_exc()
            ok = False
        return {"running": tc.is_tray_running() if ok else False,
                "message": "托盘已启动" if ok else "托盘启动失败"}

    def hide_to_tray(self) -> dict:
        """隐藏窗口到托盘；托盘没在跑就先把它拉起来，保证还有入口召回。"""
        try:
            if not tc.is_tray_running():
                try:
                    ok = tc.start_tray_app()
                except Exception:
                    traceback.print_exc()
                    ok = False
                if not ok and not tc.is_tray_running():
                    return {"ok": False, "message": "托盘启动失败，先保持窗口打开"}
            if webview.windows:
                webview.windows[0].hide()
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "message": str(e)}

    # ---- 杂项 ----
    def open_config_folder(self) -> dict:
        try:
            os.startfile(tc.BASE_DIR)      # 配置 / 协议文件都在程序目录
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # ---- 桌面链接 ----
    def rebuild_links(self) -> dict:
        try:
            r = tc.install_desktop_links()
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "message": "桌面链接创建失败", "errors": [str(e)]}
        bits = []
        kind = r.get("folder") or ""
        if kind:
            bits.append(f"文件夹→{win_link.KIND_LABEL.get(kind, kind)}")
        for name, k in (r.get("links") or {}).items():
            bits.append(f"{name}→{win_link.KIND_LABEL.get(k, k)}")
        return {
            "ok": bool(bits),
            "message": "桌面链接已更新：" + "；".join(bits) if bits else "桌面链接创建失败",
            "errors": r.get("errors") or [],
        }


# --------------------------------------------------------------- 离线模式
# 程序自身不发任何网络请求：页面用 file:// 加载，图片是本地 png，
# 没有任何 CDN / 在线字体 / 统计脚本。但内嵌的 Edge（WebView2）引擎
# 会在后台连微软的遥测和组件更新端点（实测 40.99.10.98:443，MSFT 的地址）。
# 下面把这些开关关掉，让整个进程彻底不联网。
_WEBVIEW2_OFFLINE_ARGS = " ".join([
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-breakpad",
    "--no-pings",
    "--disable-client-side-phishing-detection",
    "--disable-sync",
])


def _force_offline() -> None:
    """掐掉 WebView2 引擎自身的后台联网。

    pywebview 建控件时把 AdditionalBrowserArguments 写死成
    '--disable-features=ElasticOverscroll'，它会盖掉同名的
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS 环境变量，所以这里包一层
    EdgeChrome.__init__：等控件建好，把参数读出来、追加、再写回去。

    任何一步失败都静默跳过 —— 联网开关不该影响程序能不能打开。
    """
    os.environ.setdefault(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", _WEBVIEW2_OFFLINE_ARGS
    )
    try:
        from webview.platforms import edgechromium

        cls = edgechromium.EdgeChrome
        original = cls.__init__
        if getattr(original, "_offline_patched", False):
            return

        def patched(self, form, window, cache_dir):
            original(self, form, window, cache_dir)
            try:
                props = self.webview.CreationProperties
                args = props.AdditionalBrowserArguments or ""
                if "--disable-background-networking" not in args:
                    props.AdditionalBrowserArguments = (
                        args + " " + _WEBVIEW2_OFFLINE_ARGS
                    ).strip()
            except Exception:
                pass

        patched._offline_patched = True  # type: ignore[attr-defined]
        cls.__init__ = patched
    except Exception:
        return


def main() -> int:
    _force_offline()
    api = Api()
    webview.create_window(
        tc.UI_TITLE,
        url="file://" + _ui_path().replace("\\", "/"),
        js_api=api,
        width=1080, height=820,
        min_size=(760, 660),
        background_color="#f6f8f9",
    )
    webview.start(debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
