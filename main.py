"""
最简指纹浏览器 — Tkinter + Selenium
- 多窗口配置, 每个独立 user-data-dir
- SOCKS5 / HTTP 代理, SOCKS5 带账号密码用本地中继转
- UA / 时区 / 语言 / 平台 / 核数 / 内存 / Canvas / WebRTC
"""

import os
import sys
import json
import socket
import struct
import asyncio
import threading
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service as ChromeService
except ImportError:
    print("请先安装依赖: pip install selenium")
    sys.exit(1)

from fingerprint import random_profile, OS_PRESETS
from chrome_setup import ensure_chrome
import migrate


APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FpBrowser"
APP_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_DIR = APP_DIR / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = APP_DIR / "config.json"


# ---------------- SOCKS5 本地中继 (Chrome 不支持 SOCKS5 鉴权, 用这个绕过) ----------------

class Socks5Relay:
    def __init__(self, up_host, up_port, up_user, up_pass):
        self.up = (up_host, int(up_port))
        self.cred = (up_user or "", up_pass or "")
        self.port = None
        self.loop = None
        self.server = None
        self.thread = None

    def start(self):
        ready = threading.Event()

        def runner():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            coro = asyncio.start_server(self._handle, "127.0.0.1", 0)
            self.server = self.loop.run_until_complete(coro)
            self.port = self.server.sockets[0].getsockname()[1]
            ready.set()
            self.loop.run_forever()

        self.thread = threading.Thread(target=runner, daemon=True)
        self.thread.start()
        ready.wait(timeout=5)
        return self.port

    def stop(self):
        if self.loop:
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass

    async def _handle(self, cr, cw):
        try:
            await self._client_greet(cr, cw)
            host, port = await self._client_req(cr)
            ur, uw = await self._connect_upstream(host, port)
            cw.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await cw.drain()
            await asyncio.gather(self._pipe(cr, uw), self._pipe(ur, cw))
        except Exception:
            pass
        finally:
            try:
                cw.close()
            except Exception:
                pass

    async def _client_greet(self, cr, cw):
        ver, n = struct.unpack("BB", await cr.readexactly(2))
        await cr.readexactly(n)
        cw.write(b"\x05\x00")
        await cw.drain()

    async def _client_req(self, cr):
        head = await cr.readexactly(4)
        atyp = head[3]
        if atyp == 1:
            addr = ".".join(str(b) for b in await cr.readexactly(4))
        elif atyp == 3:
            l = (await cr.readexactly(1))[0]
            addr = (await cr.readexactly(l)).decode()
        elif atyp == 4:
            raw = await cr.readexactly(16)
            addr = socket.inet_ntop(socket.AF_INET6, raw)
        else:
            raise Exception("bad atyp")
        port = struct.unpack(">H", await cr.readexactly(2))[0]
        return addr, port

    async def _connect_upstream(self, host, port):
        ur, uw = await asyncio.open_connection(*self.up)
        if self.cred[0]:
            uw.write(b"\x05\x02\x00\x02")
        else:
            uw.write(b"\x05\x01\x00")
        await uw.drain()
        resp = await ur.readexactly(2)
        method = resp[1]
        if method == 0x02:
            u = self.cred[0].encode()
            p = self.cred[1].encode()
            uw.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
            await uw.drain()
            ar = await ur.readexactly(2)
            if ar[1] != 0x00:
                raise Exception("upstream auth fail")
        elif method != 0x00:
            raise Exception(f"upstream method {method} not supported")
        host_b = host.encode()
        uw.write(b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b + struct.pack(">H", port))
        await uw.drain()
        rh = await ur.readexactly(4)
        if rh[1] != 0x00:
            raise Exception(f"upstream rep={rh[1]}")
        atyp = rh[3]
        if atyp == 1:
            await ur.readexactly(4 + 2)
        elif atyp == 3:
            l = (await ur.readexactly(1))[0]
            await ur.readexactly(l + 2)
        elif atyp == 4:
            await ur.readexactly(16 + 2)
        return ur, uw

    async def _pipe(self, r, w):
        try:
            while True:
                data = await r.read(16384)
                if not data:
                    break
                w.write(data)
                await w.drain()
        except Exception:
            pass
        try:
            w.close()
        except Exception:
            pass


# ---------------- Chrome 启动 ----------------


def launch_browser(profile, chrome_path=None, driver_path=None, headless=False):
    relay = None
    proxy_arg = None

    if profile.get("proxy_enable") and profile.get("proxy_host"):
        ptype = (profile.get("proxy_type") or "socks5").lower()
        host = profile["proxy_host"].strip()
        port = str(profile["proxy_port"]).strip()
        user = (profile.get("proxy_user") or "").strip()
        pwd = (profile.get("proxy_pass") or "").strip()
        if ptype == "socks5" and user:
            relay = Socks5Relay(host, port, user, pwd)
            local_port = relay.start()
            proxy_arg = f"socks5://127.0.0.1:{local_port}"
        else:
            proxy_arg = f"{ptype}://{host}:{port}"

    options = Options()
    if chrome_path:
        options.binary_location = chrome_path

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")

    user_data_dir = PROFILES_DIR / profile["name"]
    user_data_dir.mkdir(exist_ok=True)
    options.add_argument(f"--user-data-dir={user_data_dir}")

    if proxy_arg:
        options.add_argument(f"--proxy-server={proxy_arg}")

    ua = (profile.get("user_agent") or "").strip()
    if ua:
        options.add_argument(f"--user-agent={ua}")

    lang = (profile.get("language") or "").strip()
    if lang:
        options.add_argument(f"--lang={lang}")

    if profile.get("webrtc_block", True):
        options.add_argument("--webrtc-ip-handling-policy=disable_non_proxied_udp")
        options.add_argument("--force-webrtc-ip-handling-policy")

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if driver_path:
        driver = webdriver.Chrome(options=options, service=ChromeService(executable_path=driver_path))
    else:
        driver = webdriver.Chrome(options=options)

    tz = (profile.get("timezone") or "").strip()
    if tz:
        try:
            driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": tz})
        except Exception:
            pass

    if lang:
        try:
            driver.execute_cdp_cmd("Emulation.setLocaleOverride", {"locale": lang})
        except Exception:
            pass

    js = ["Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"]
    plat = (profile.get("platform") or "").strip()
    if plat:
        js.append(f"Object.defineProperty(navigator,'platform',{{get:()=>'{plat}'}});")
    hwc = (profile.get("hardware_concurrency") or "").strip()
    if hwc.isdigit():
        js.append(f"Object.defineProperty(navigator,'hardwareConcurrency',{{get:()=>{int(hwc)}}});")
    mem = (profile.get("device_memory") or "").strip()
    if mem.isdigit():
        js.append(f"Object.defineProperty(navigator,'deviceMemory',{{get:()=>{int(mem)}}});")

    sw = (profile.get("screen_width") or "").strip()
    sh = (profile.get("screen_height") or "").strip()
    if sw.isdigit() and sh.isdigit():
        js.append(f"""
(function(){{
  const w = {int(sw)}, h = {int(sh)};
  Object.defineProperty(screen,'width',{{get:()=>w}});
  Object.defineProperty(screen,'height',{{get:()=>h}});
  Object.defineProperty(screen,'availWidth',{{get:()=>w}});
  Object.defineProperty(screen,'availHeight',{{get:()=>h - 40}});
}})();
""")

    ua_plat = (profile.get("ua_data_platform") or "").strip()
    ua_pver = (profile.get("ua_data_platform_version") or "").strip()
    chrome_ver = (profile.get("chrome_version") or "").strip()
    if ua_plat and chrome_ver:
        major = chrome_ver.split(".")[0]
        js.append(f"""
(function(){{
  const brands = [
    {{brand:'Chromium', version:'{major}'}},
    {{brand:'Google Chrome', version:'{major}'}},
    {{brand:'Not?A_Brand', version:'24'}}
  ];
  const data = {{
    brands: brands,
    mobile: false,
    platform: '{ua_plat}',
    getHighEntropyValues: (hints) => Promise.resolve({{
      architecture: 'x86', bitness: '64', model: '', mobile: false,
      platform: '{ua_plat}', platformVersion: '{ua_pver}',
      uaFullVersion: '{chrome_ver}', wow64: false,
      fullVersionList: brands.map(b => ({{brand: b.brand, version: '{chrome_ver}'}}))
    }}),
    toJSON: () => ({{brands: brands, mobile: false, platform: '{ua_plat}'}})
  }};
  Object.defineProperty(navigator,'userAgentData',{{get:()=>data}});
}})();
""")

    if profile.get("canvas_noise", True):
        js.append("""
(function(){
  const orig = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function(...a){
    try{
      const ctx = this.getContext('2d');
      if(ctx){
        const d = ctx.getImageData(0,0,this.width,this.height);
        for(let i=0;i<d.data.length;i+=137){ d.data[i] ^= 1; }
        ctx.putImageData(d,0,0);
      }
    }catch(e){}
    return orig.apply(this,a);
  };
})();
""")
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "\n".join(js)})

    pending = profile.get("_pending_cookies")
    if pending and os.path.exists(pending):
        try:
            with open(pending, encoding="utf-8") as f:
                cookies = json.load(f)
            for c in cookies:
                try:
                    driver.execute_cdp_cmd("Network.setCookie", migrate.normalize_cookie_for_setcookie(c))
                except Exception:
                    pass
        except Exception:
            pass

    start_url = (profile.get("start_url") or "").strip()
    if start_url:
        driver.get(start_url)

    return driver, relay


# ---------------- 配置 ----------------

DEFAULT_PROFILE = {
    "name": "窗口1",
    "proxy_enable": True,
    "proxy_type": "socks5",
    "proxy_host": "",
    "proxy_port": "",
    "proxy_user": "",
    "proxy_pass": "",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "language": "en-US",
    "timezone": "America/New_York",
    "platform": "Win32",
    "hardware_concurrency": "8",
    "device_memory": "8",
    "webrtc_block": True,
    "canvas_noise": True,
    "start_url": "https://www.browserscan.net/",
}


def load_profiles():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_profiles(profiles):
    CONFIG_FILE.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------- GUI ----------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("指纹浏览器")
        self.geometry("820x600")
        self.profiles = load_profiles()
        self._relays = []
        self.chrome_path = None
        self.chromedriver_path = None
        self._build()
        self._refresh_list()
        if self.profiles:
            self.listbox.selection_set(0)
            self._on_select(None)
        self.after(200, self._init_chrome)

    def _init_chrome(self):
        try:
            self.chrome_path, self.chromedriver_path = ensure_chrome(APP_DIR, parent=self)
        except Exception as e:
            messagebox.showerror("Chrome 检测失败", f"{e}\n\n后续启动窗口时会失败, 请安装 Chrome 后重启程序。")

    def _build(self):
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=8, pady=8)
        ttk.Label(left, text="窗口列表 (Ctrl/Shift 多选)").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=26, height=24, selectmode=tk.EXTENDED)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        single = ttk.LabelFrame(left, text="单条")
        single.pack(fill="x", pady=(6, 2))
        ttk.Button(single, text="新建", command=self._new, width=6).grid(row=0, column=0, padx=2, pady=2)
        ttk.Button(single, text="保存", command=self._save, width=6).grid(row=0, column=1, padx=2, pady=2)
        ttk.Button(single, text="启动", command=self._launch, width=6).grid(row=0, column=2, padx=2, pady=2)

        batch = ttk.LabelFrame(left, text="批量")
        batch.pack(fill="x", pady=2)
        ttk.Button(batch, text="批量启动", command=self._batch_launch).grid(row=0, column=0, padx=2, pady=2, sticky="we")
        ttk.Button(batch, text="批量删除", command=self._del).grid(row=0, column=1, padx=2, pady=2, sticky="we")
        ttk.Button(batch, text="批量改代理", command=self._batch_proxy).grid(row=1, column=0, columnspan=2, padx=2, pady=2, sticky="we")
        batch.columnconfigure(0, weight=1)
        batch.columnconfigure(1, weight=1)

        migrate = ttk.LabelFrame(left, text="账号平移")
        migrate.pack(fill="x", pady=2)
        ttk.Button(migrate, text="导出选中", command=self._export).grid(row=0, column=0, padx=2, pady=2, sticky="we")
        ttk.Button(migrate, text="导入 zip", command=self._import).grid(row=0, column=1, padx=2, pady=2, sticky="we")
        migrate.columnconfigure(0, weight=1)
        migrate.columnconfigure(1, weight=1)

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        self._right = right
        self._editable_widgets = []

        self.vars = {}
        rows = [
            ("name", "窗口名称"),
            ("proxy_type", "代理类型 (socks5 / http)"),
            ("proxy_host", "代理 IP"),
            ("proxy_port", "代理端口"),
            ("proxy_user", "代理账号 (可空)"),
            ("proxy_pass", "代理密码 (可空)"),
            ("user_agent", "User-Agent"),
            ("language", "语言 (例: en-US, zh-CN)"),
            ("timezone", "时区 (例: America/New_York)"),
            ("platform", "Platform (Win32 / MacIntel)"),
            ("hardware_concurrency", "CPU 核数"),
            ("device_memory", "内存 GB"),
            ("screen_width", "屏幕宽"),
            ("screen_height", "屏幕高"),
            ("start_url", "启动页"),
        ]
        for i, (k, label) in enumerate(rows):
            ttk.Label(right, text=label).grid(row=i, column=0, sticky="w", padx=4, pady=3)
            v = tk.StringVar()
            e = ttk.Entry(right, textvariable=v, width=62)
            e.grid(row=i, column=1, sticky="we", padx=4, pady=3)
            self.vars[k] = v
            self._editable_widgets.append(e)

        i = len(rows)
        self.proxy_enable_var = tk.BooleanVar(value=True)
        cb1 = ttk.Checkbutton(right, text="启用代理", variable=self.proxy_enable_var)
        cb1.grid(row=i, column=1, sticky="w")
        self._editable_widgets.append(cb1)
        i += 1
        self.webrtc_var = tk.BooleanVar(value=True)
        cb2 = ttk.Checkbutton(right, text="阻止 WebRTC 真实 IP 泄露", variable=self.webrtc_var)
        cb2.grid(row=i, column=1, sticky="w")
        self._editable_widgets.append(cb2)
        i += 1
        self.canvas_var = tk.BooleanVar(value=True)
        cb3 = ttk.Checkbutton(right, text="Canvas 添加噪声", variable=self.canvas_var)
        cb3.grid(row=i, column=1, sticky="w")
        self._editable_widgets.append(cb3)

        right.columnconfigure(1, weight=1)

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for p in self.profiles:
            self.listbox.insert(tk.END, p.get("name", "(未命名)"))

    def _sel(self):
        s = self.listbox.curselection()
        return s[0] if s else None

    def _sels(self):
        return list(self.listbox.curselection())

    def _on_select(self, _):
        sels = self._sels()
        if len(sels) == 1:
            p = self.profiles[sels[0]]
            for k, v in self.vars.items():
                v.set(str(p.get(k, "")))
            self.proxy_enable_var.set(p.get("proxy_enable", True))
            self.webrtc_var.set(p.get("webrtc_block", True))
            self.canvas_var.set(p.get("canvas_noise", True))
            self._set_form_state("normal")
        elif len(sels) > 1:
            self._set_form_state("disabled")
            for k, v in self.vars.items():
                v.set(f"(已选 {len(sels)} 个, 编辑请只选一个)" if k == "name" else "")

    def _set_form_state(self, state):
        for w in self._editable_widgets:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass

    def _collect(self):
        p = {k: v.get() for k, v in self.vars.items()}
        p["proxy_enable"] = self.proxy_enable_var.get()
        p["webrtc_block"] = self.webrtc_var.get()
        p["canvas_noise"] = self.canvas_var.get()
        return p

    def _new(self):
        os_key = self._pick_os()
        if not os_key:
            return
        p = random_profile(os_key=os_key, name=f"窗口{len(self.profiles) + 1}")
        self.profiles.append(p)
        save_profiles(self.profiles)
        self._refresh_list()
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(len(self.profiles) - 1)
        self._on_select(None)

    def _pick_os(self):
        """弹 modal 让用户选 OS 套餐, 取消返回 None。"""
        win = tk.Toplevel(self)
        win.title("选择 OS 套餐")
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)
        ttk.Label(win, text="新建窗口的指纹套餐:", padding=10).pack(anchor="w")
        var = tk.StringVar(value="Win10")
        for key in OS_PRESETS:
            ttk.Radiobutton(win, text=key, variable=var, value=key).pack(anchor="w", padx=20)
        result = {"v": None}

        def ok():
            result["v"] = var.get()
            win.destroy()

        def cancel():
            win.destroy()

        bar = ttk.Frame(win)
        bar.pack(pady=10)
        ttk.Button(bar, text="确定", command=ok).pack(side="left", padx=6)
        ttk.Button(bar, text="取消", command=cancel).pack(side="left", padx=6)
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")
        self.wait_window(win)
        return result["v"]

    def _del(self):
        sels = self._sels()
        if not sels:
            messagebox.showinfo("提示", "请先选择要删除的窗口")
            return
        names = [self.profiles[i]["name"] for i in sels]
        msg = f"确定删除 {names[0]} ?" if len(sels) == 1 else f"确定删除 {len(sels)} 个窗口?\n\n" + ", ".join(names[:8]) + ("..." if len(names) > 8 else "")
        if not messagebox.askyesno("删除", msg):
            return
        for i in sorted(sels, reverse=True):
            self.profiles.pop(i)
        save_profiles(self.profiles)
        self._refresh_list()

    def _save(self):
        sels = self._sels()
        if len(sels) != 1:
            messagebox.showinfo("提示", "请选择单个窗口再保存(多选下表单已锁定)")
            return
        idx = sels[0]
        self.profiles[idx] = self._collect()
        save_profiles(self.profiles)
        self._refresh_list()
        self.listbox.selection_set(idx)
        messagebox.showinfo("保存", "已保存")

    def _launch(self):
        sels = self._sels()
        if len(sels) != 1:
            messagebox.showinfo("提示", "请选择单个窗口再启动(批量请用 批量启动)")
            return
        idx = sels[0]
        self.profiles[idx] = self._collect()
        save_profiles(self.profiles)
        self._spawn(dict(self.profiles[idx]))

    def _batch_launch(self):
        sels = self._sels()
        if not sels:
            messagebox.showinfo("提示", "请先选择要启动的窗口")
            return
        for i in sels:
            self._spawn(dict(self.profiles[i]))

    def _spawn(self, profile):
        pending = profile.get("_pending_cookies")
        name = profile.get("name")

        def run():
            relay = None
            try:
                driver, relay = launch_browser(profile, chrome_path=self.chrome_path, driver_path=self.chromedriver_path)
                if pending:
                    self.after(0, lambda: self._clear_pending(name, pending))
                if relay:
                    self._relays.append(relay)
                try:
                    while True:
                        _ = driver.window_handles
                        threading.Event().wait(2)
                except Exception:
                    pass
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(f"启动失败 [{profile.get('name')}]", str(e)))
            finally:
                if relay:
                    relay.stop()
        threading.Thread(target=run, daemon=True).start()

    def _batch_proxy(self):
        sels = self._sels()
        if not sels:
            messagebox.showinfo("提示", "请先选择要改代理的窗口")
            return
        win = tk.Toplevel(self)
        win.title(f"批量改代理 ({len(sels)} 个窗口)")
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)

        fields = [
            ("proxy_type", "类型 (socks5/http)", "socks5"),
            ("proxy_host", "IP", ""),
            ("proxy_port", "端口", ""),
            ("proxy_user", "账号 (可空)", ""),
            ("proxy_pass", "密码 (可空)", ""),
        ]
        entries = {}
        for i, (k, label, default) in enumerate(fields):
            ttk.Label(win, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            v = tk.StringVar(value=default)
            ttk.Entry(win, textvariable=v, width=36).grid(row=i, column=1, padx=8, pady=4)
            entries[k] = v

        def apply():
            for i in sels:
                for k, v in entries.items():
                    self.profiles[i][k] = v.get().strip()
                self.profiles[i]["proxy_enable"] = True
            save_profiles(self.profiles)
            self._refresh_list()
            for i in sels:
                self.listbox.selection_set(i)
            win.destroy()
            messagebox.showinfo("完成", f"已更新 {len(sels)} 个窗口的代理")

        bar = ttk.Frame(win)
        bar.grid(row=len(fields), column=0, columnspan=2, pady=10)
        ttk.Button(bar, text="应用", command=apply).pack(side="left", padx=8)
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="left", padx=8)
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")

    def _clear_pending(self, name, pending_path):
        for p in self.profiles:
            if p.get("name") == name and p.get("_pending_cookies") == pending_path:
                p.pop("_pending_cookies", None)
        save_profiles(self.profiles)
        try:
            os.unlink(pending_path)
        except OSError:
            pass

    def _export(self):
        sels = self._sels()
        if not sels:
            messagebox.showinfo("提示", "请先选择要导出的窗口")
            return
        if not self.chrome_path:
            messagebox.showerror("无 Chrome", "Chrome 未就绪, 无法启动 headless 抓 cookie")
            return
        default_name = datetime.now().strftime("fp-export-%Y%m%d-%H%M%S.zip")
        zip_path = filedialog.asksaveasfilename(
            title="导出到", defaultextension=".zip", initialfile=default_name,
            filetypes=[("zip 包", "*.zip")],
        )
        if not zip_path:
            return

        include_history = messagebox.askyesno("是否包含历史/书签", "是否包含历史/书签? (会让包变大)")
        include_cache = False

        items = [dict(self.profiles[i]) for i in sels]
        self._run_progress("导出中", lambda cb: migrate.export_profiles(
            items, Path(zip_path), PROFILES_DIR, self.chrome_path, self.chromedriver_path,
            include_history=include_history, include_cache=include_cache, progress_cb=cb,
        ), self._after_export)

    def _after_export(self, ret):
        success, errors = ret
        msg = f"导出完成: {success} 个窗口"
        if errors:
            msg += "\n\n错误:\n" + "\n".join(errors[:10])
        messagebox.showinfo("导出", msg)

    def _import(self):
        zip_path = filedialog.askopenfilename(
            title="选择导出包", filetypes=[("zip 包", "*.zip")],
        )
        if not zip_path:
            return
        self._run_progress("导入中", lambda cb: migrate.import_zip(
            Path(zip_path), self.profiles, PROFILES_DIR, APP_DIR, progress_cb=cb,
        ), self._after_import)

    def _after_import(self, ret):
        added, errors = ret
        save_profiles(self.profiles)
        self._refresh_list()
        msg = f"导入完成: {len(added)} 个窗口"
        if added:
            msg += "\n" + ", ".join(added[:10]) + ("..." if len(added) > 10 else "")
        if errors:
            msg += "\n\n错误:\n" + "\n".join(errors[:10])
        messagebox.showinfo("导入", msg)

    def _run_progress(self, title, work, after):
        """通用进度对话框 + 后台线程。work(progress_cb) 返回结果, after(result) 在主线程调用。"""
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)
        label = ttk.Label(win, text="准备中...", padding=10)
        label.pack()
        bar = ttk.Progressbar(win, length=380, mode="determinate")
        bar.pack(padx=20, pady=8)
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")

        state = {"ret": None, "err": None}

        def progress(i, total, name):
            def update():
                bar["maximum"] = max(total, 1)
                bar["value"] = i
                label.config(text=f"[{i}/{total}] {name}")
            self.after(0, update)

        def worker():
            try:
                state["ret"] = work(progress)
            except Exception as e:
                state["err"] = e

            def finish():
                win.destroy()
                if state["err"]:
                    messagebox.showerror(title, f"失败: {state['err']}")
                elif after:
                    after(state["ret"])
            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    App().mainloop()
