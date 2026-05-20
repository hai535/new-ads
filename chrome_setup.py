"""
Chrome 自动下载 (chrome-for-testing) — 无 Chrome 时给装一份纯净 Chrome 到 APP_DIR/chrome-bin/。

设计:
- 优先用本地 APP_DIR/chrome-bin/ 下的 chrome
- 其次用系统 Chrome
- 都没有 → 下载 chrome-for-testing Stable Win64 zip
- 同时下载对应版本 chromedriver,避免 selenium 联网二次下载
"""

import os
import json
import zipfile
import shutil
import urllib.request
import threading
from pathlib import Path


CFT_JSON_URL = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"


def _system_chrome():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


def _local_chrome(chrome_dir: Path):
    """查 chrome-bin/ 下的 chrome.exe (Windows) 或 chrome (Linux/Mac)。"""
    for name in ("chrome.exe", "chrome"):
        for sub in ("chrome-win64", "chrome-linux64", "chrome-mac-x64", "chrome-mac-arm64", ""):
            p = chrome_dir / sub / name
            if p.exists():
                return str(p)
    return None


def _local_chromedriver(chrome_dir: Path):
    for name in ("chromedriver.exe", "chromedriver"):
        for sub in ("chromedriver-win64", "chromedriver-linux64", "chromedriver-mac-x64", "chromedriver-mac-arm64", ""):
            p = chrome_dir / sub / name
            if p.exists():
                return str(p)
    return None


def _platform_key():
    import sys
    if sys.platform.startswith("win"):
        return "win64"
    if sys.platform == "darwin":
        import platform
        return "mac-arm64" if platform.machine() == "arm64" else "mac-x64"
    return "linux64"


def _fetch_cft_urls():
    """从 chrome-for-testing JSON 拿 Stable 通道的 chrome / chromedriver 下载 URL。"""
    with urllib.request.urlopen(CFT_JSON_URL, timeout=30) as resp:
        data = json.loads(resp.read())
    stable = data["channels"]["Stable"]
    version = stable["version"]
    plat = _platform_key()
    chrome_url = None
    driver_url = None
    for item in stable["downloads"].get("chrome", []):
        if item["platform"] == plat:
            chrome_url = item["url"]
            break
    for item in stable["downloads"].get("chromedriver", []):
        if item["platform"] == plat:
            driver_url = item["url"]
            break
    if not chrome_url or not driver_url:
        raise RuntimeError(f"chrome-for-testing 没有 {plat} 平台资源")
    return version, chrome_url, driver_url


def _download_with_progress(url: str, dest: Path, progress_cb=None):
    with urllib.request.urlopen(url, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", "0"))
        got = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress_cb:
                    progress_cb(got, total)


def _unzip(zip_path: Path, dest_dir: Path):
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest_dir)
    zip_path.unlink(missing_ok=True)


def ensure_chrome(app_dir: Path, parent=None):
    """
    返回 (chrome_path, chromedriver_path)。
    chromedriver_path 可能为 None (走 selenium 自管理)。
    """
    chrome_dir = app_dir / "chrome-bin"
    chrome_dir.mkdir(parents=True, exist_ok=True)

    local = _local_chrome(chrome_dir)
    if local:
        return local, _local_chromedriver(chrome_dir)

    system = _system_chrome()
    if system:
        return system, None

    if parent is not None:
        import tkinter as tk
        from tkinter import messagebox
        ok = messagebox.askyesno(
            "下载 Chrome",
            "未检测到 Chrome 浏览器, 需下载 chrome-for-testing (约 150MB)。\n是否现在下载?",
            parent=parent,
        )
        if not ok:
            raise RuntimeError("用户取消 Chrome 下载")

    return _do_download(chrome_dir, parent)


def _do_download(chrome_dir: Path, parent):
    """带进度对话框的下载 (parent 为 None 则纯命令行)。"""
    version, chrome_url, driver_url = _fetch_cft_urls()

    state = {"done": False, "err": None}

    if parent is not None:
        import tkinter as tk
        from tkinter import ttk
        win = tk.Toplevel(parent)
        win.title(f"下载 Chrome {version}")
        win.transient(parent)
        win.grab_set()
        win.resizable(False, False)
        ttk.Label(win, text=f"chrome-for-testing {version}", padding=10).pack()
        label = ttk.Label(win, text="准备中...")
        label.pack(padx=20)
        bar = ttk.Progressbar(win, length=360, mode="determinate")
        bar.pack(padx=20, pady=10)

        def update(stage, got, total):
            pct = (got / total * 100) if total else 0
            label.config(text=f"{stage}: {got // (1024*1024)} / {total // (1024*1024)} MB")
            bar["value"] = pct

        win.update_idletasks()
    else:
        def update(stage, got, total):
            print(f"\r{stage}: {got // (1024*1024)} / {total // (1024*1024)} MB", end="", flush=True)

    def worker():
        try:
            chrome_zip = chrome_dir / "chrome.zip"
            driver_zip = chrome_dir / "chromedriver.zip"
            _download_with_progress(
                chrome_url, chrome_zip,
                lambda g, t: (parent.after(0, lambda: update("Chrome", g, t)) if parent else update("Chrome", g, t)),
            )
            _download_with_progress(
                driver_url, driver_zip,
                lambda g, t: (parent.after(0, lambda: update("chromedriver", g, t)) if parent else update("chromedriver", g, t)),
            )
            _unzip(chrome_zip, chrome_dir)
            _unzip(driver_zip, chrome_dir)
        except Exception as e:
            state["err"] = e
        finally:
            state["done"] = True

    if parent is not None:
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while not state["done"]:
            win.update()
            threading.Event().wait(0.05)
        win.destroy()
    else:
        worker()

    if state["err"]:
        raise state["err"]

    chrome_path = _local_chrome(chrome_dir)
    driver_path = _local_chromedriver(chrome_dir)
    if not chrome_path:
        raise RuntimeError("解压后未找到 chrome 可执行文件")
    return chrome_path, driver_path
