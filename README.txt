指纹浏览器 - 最简版
====================

依赖
----
- Windows + Python 3.10+
- 已安装 Google Chrome
- selenium 4.15+ (Selenium Manager 会自动下 chromedriver, 无需手动)

打包成 exe
----------
1. 在 Windows 上把整个 fp-browser 目录拷过去
2. 双击 build.bat
3. 输出: dist\FpBrowser.exe (单文件, 双击即用)

直接运行 (不打包)
-----------------
    pip install -r requirements.txt
    python main.py

功能
----
- 多窗口管理, 每个窗口独立 user-data-dir (cookie / 缓存隔离)
- 代理: SOCKS5 / HTTP, SOCKS5 带账号密码也支持 (内置本地中继)
- 指纹: User-Agent / 时区 / 语言 / Platform / CPU 核数 / 内存 / Canvas 噪声
- WebRTC 真实 IP 泄露防护

配置存储位置
------------
    %LOCALAPPDATA%\FpBrowser\config.json     窗口配置
    %LOCALAPPDATA%\FpBrowser\profiles\<name>\  各窗口的 Chrome 数据

验证指纹是否生效
----------------
启动后默认打开 https://www.browserscan.net/ , 或换成
https://abrahamjuliot.github.io/creepjs/ 看更详细的报告.

注意
----
- 这是一个最简实现, 用来过基础指纹检测够用. 想过专业反爬商业站点
  (CreepJS / FingerprintJS Pro), 还需要 GPU / 字体 / WebGL hash 这些
  深度伪造, 那就不是"最简"范畴了.
- 浏览器关闭后, 程序里的列表不会自动刷新; 重启程序即可.
