"""
账号平移 — 多窗口配置 + 登录态 跨机器迁移。

策略 (避开 Chrome ABE):
- 导出: headless 启动 Chrome -> CDP Network.getAllCookies 拉明文 cookie -> driver.quit
        -> 拷 LocalStorage / IndexedDB / Session Storage 等非加密目录 -> 打 zip
- 导入: 解 zip -> 拷数据目录到目标 user-data-dir -> 标记 _pending_cookies, 首次启动时
        通过 CDP Network.setCookie 注入, Chrome 后续会用目标机器 ABE 重新持久化
"""

import os
import json
import shutil
import zipfile
import tempfile
import time
import uuid
import threading
from pathlib import Path
from datetime import datetime


EXPORT_VERSION = 1
COPY_SUBDIRS = [
    "Local Storage",
    "IndexedDB",
    "Session Storage",
    "Local Extension Settings",
    "Extension Storage",
]
OPTIONAL_HISTORY_FILES = ["History", "Bookmarks", "Favicons", "Top Sites", "Visited Links"]
OPTIONAL_CACHE_DIRS = ["Cache", "Code Cache"]


def _safe_copytree(src: Path, dst: Path):
    if src.exists():
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _export_one(profile: dict, profiles_dir: Path, chrome_path: str, driver_path: str,
                staging: Path, include_history: bool, include_cache: bool):
    """导出单个窗口到 staging/<name>/。返回 None 或错误信息。"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service as ChromeService

    name = profile["name"]
    user_data_dir = profiles_dir / name
    if not user_data_dir.exists():
        return f"[{name}] user-data-dir 不存在, 跳过"

    out = staging / name
    out.mkdir(parents=True, exist_ok=True)

    cookies = []
    try:
        opts = Options()
        if chrome_path:
            opts.binary_location = chrome_path
        opts.add_argument(f"--user-data-dir={user_data_dir}")
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-startup-window")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        if driver_path:
            driver = webdriver.Chrome(options=opts, service=ChromeService(executable_path=driver_path))
        else:
            driver = webdriver.Chrome(options=opts)
        try:
            result = driver.execute_cdp_cmd("Network.getAllCookies", {})
            cookies = result.get("cookies", [])
        finally:
            driver.quit()
    except Exception as e:
        return f"[{name}] 启动 headless Chrome 失败 (是否窗口正在前台运行?): {e}"

    time.sleep(0.8)

    (out / "cookies.json").write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

    default = user_data_dir / "Default"
    if not default.exists():
        return f"[{name}] 没有 Default profile 目录"

    data_out = out / "Default"
    data_out.mkdir(exist_ok=True)
    for sub in COPY_SUBDIRS:
        _safe_copytree(default / sub, data_out / sub)
    if include_history:
        for f in OPTIONAL_HISTORY_FILES:
            _safe_copytree(default / f, data_out / f)
    if include_cache:
        for d in OPTIONAL_CACHE_DIRS:
            _safe_copytree(default / d, data_out / d)
    return None


def export_profiles(profiles_subset: list, zip_path: Path, profiles_dir: Path,
                    chrome_path: str, driver_path: str,
                    include_history: bool = False, include_cache: bool = False,
                    progress_cb=None):
    """profiles_subset: 选中的完整 profile dict 列表。返回 (success, errors)。"""
    errors = []
    success = 0
    with tempfile.TemporaryDirectory(prefix="fp-export-") as tmp:
        staging = Path(tmp)
        for i, p in enumerate(profiles_subset):
            if progress_cb:
                progress_cb(i, len(profiles_subset), p.get("name", "?"))
            err = _export_one(p, profiles_dir, chrome_path, driver_path, staging,
                              include_history, include_cache)
            if err:
                errors.append(err)
            else:
                success += 1

        manifest = {
            "version": EXPORT_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "windows": [p["name"] for p in profiles_subset if (staging / p["name"]).exists()],
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(staging):
                root_p = Path(root)
                for f in files:
                    full = root_p / f
                    zf.write(full, full.relative_to(staging))

        if progress_cb:
            progress_cb(len(profiles_subset), len(profiles_subset), "done")
    return success, errors


def import_zip(zip_path: Path, profiles: list, profiles_dir: Path, app_dir: Path,
               progress_cb=None):
    """解 zip 写入 profiles 与 user-data-dir。返回 (added_names, errors)。"""
    errors = []
    added = []
    pending_dir = app_dir / "pending-cookies"
    pending_dir.mkdir(parents=True, exist_ok=True)
    existing_names = {p["name"] for p in profiles}

    with tempfile.TemporaryDirectory(prefix="fp-import-") as tmp:
        tmp_p = Path(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_p)

        manifest_file = tmp_p / "manifest.json"
        if not manifest_file.exists():
            return added, ["zip 中找不到 manifest.json, 可能不是 fp-browser 导出的包"]
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        win_names = manifest.get("windows", [])

        for i, src_name in enumerate(win_names):
            if progress_cb:
                progress_cb(i, len(win_names), src_name)
            src = tmp_p / src_name
            if not src.exists():
                errors.append(f"[{src_name}] 在 zip 内找不到目录")
                continue
            try:
                profile = json.loads((src / "profile.json").read_text(encoding="utf-8"))
            except Exception as e:
                errors.append(f"[{src_name}] profile.json 读取失败: {e}")
                continue

            new_name = src_name
            n = 2
            while new_name in existing_names:
                new_name = f"{src_name} (导入{n})" if n > 2 else f"{src_name} (导入)"
                n += 1
            profile["name"] = new_name
            existing_names.add(new_name)

            target_default = profiles_dir / new_name / "Default"
            target_default.mkdir(parents=True, exist_ok=True)
            src_default = src / "Default"
            if src_default.exists():
                for child in src_default.iterdir():
                    _safe_copytree(child, target_default / child.name)

            cookies_src = src / "cookies.json"
            if cookies_src.exists():
                pending_file = pending_dir / f"{uuid.uuid4().hex}.json"
                shutil.copy2(cookies_src, pending_file)
                profile["_pending_cookies"] = str(pending_file)

            profiles.append(profile)
            added.append(new_name)

        if progress_cb:
            progress_cb(len(win_names), len(win_names), "done")
    return added, errors


def normalize_cookie_for_setcookie(c: dict) -> dict:
    """getAllCookies 输出 -> setCookie 输入。"""
    out = {
        "name": c["name"],
        "value": c["value"],
        "domain": c.get("domain", ""),
        "path": c.get("path", "/"),
        "secure": c.get("secure", False),
        "httpOnly": c.get("httpOnly", False),
    }
    if "sameSite" in c and c["sameSite"]:
        out["sameSite"] = c["sameSite"]
    exp = c.get("expires")
    if exp and exp > 0:
        out["expires"] = float(exp)
    return out
