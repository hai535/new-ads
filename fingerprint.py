"""
新建窗口的随机指纹生成。
按 OS 套餐随机:同套餐内 UA / platform / 核数 / 内存 / 屏幕 / userAgentData 相互自洽,
避免出现 Mac UA + Win32 platform 这种穿帮组合。
"""

import random


OS_PRESETS = {
    "Win10": {
        "ua_tpl": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
        "platform": "Win32",
        "hwc": [4, 6, 8, 12, 16],
        "mem": [4, 8, 16, 32],
        "screens": [(1920, 1080), (1536, 864), (1366, 768), (2560, 1440)],
        "ua_data_platform": "Windows",
        "ua_data_platform_version": "10.0.0",
    },
    "Win11": {
        "ua_tpl": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
        "platform": "Win32",
        "hwc": [4, 6, 8, 12, 16, 20],
        "mem": [8, 16, 32],
        "screens": [(1920, 1080), (2560, 1440), (3840, 2160), (1536, 864)],
        "ua_data_platform": "Windows",
        "ua_data_platform_version": "15.0.0",
    },
    "macOS": {
        "ua_tpl": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
        "platform": "MacIntel",
        "hwc": [4, 8, 10, 12],
        "mem": [8, 16, 32],
        "screens": [(1440, 900), (1680, 1050), (1920, 1080), (2560, 1600)],
        "ua_data_platform": "macOS",
        "ua_data_platform_version": "14.5.0",
    },
}


CHROME_VERS = [
    "122.0.6261.95",
    "123.0.6312.106",
    "124.0.6367.91",
    "125.0.6422.141",
    "126.0.6478.126",
    "127.0.6533.99",
    "128.0.6613.119",
    "129.0.6668.89",
    "130.0.6723.69",
]


def random_profile(os_key: str = "Win10", name: str | None = None) -> dict:
    """生成一套自洽的随机指纹 profile。其它非指纹字段使用占位/默认。"""
    preset = OS_PRESETS.get(os_key) or OS_PRESETS["Win10"]
    ver = random.choice(CHROME_VERS)
    w, h = random.choice(preset["screens"])

    return {
        "name": name or "窗口",
        "os_preset": os_key,
        "proxy_enable": True,
        "proxy_type": "socks5",
        "proxy_host": "",
        "proxy_port": "",
        "proxy_user": "",
        "proxy_pass": "",
        "user_agent": preset["ua_tpl"].format(ver=ver),
        "language": "en-US",
        "timezone": "America/New_York",
        "platform": preset["platform"],
        "hardware_concurrency": str(random.choice(preset["hwc"])),
        "device_memory": str(random.choice(preset["mem"])),
        "screen_width": str(w),
        "screen_height": str(h),
        "ua_data_platform": preset["ua_data_platform"],
        "ua_data_platform_version": preset["ua_data_platform_version"],
        "chrome_version": ver,
        "webrtc_block": True,
        "canvas_noise": True,
        "start_url": "https://www.browserscan.net/",
    }
