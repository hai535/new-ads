; FpBrowser NSIS 安装脚本
; makensis -DSRCDIR=/tmp/fp-staging/fp-browser-portable setup.nsi

!ifndef SRCDIR
  !define SRCDIR "/tmp/fp-staging/fp-browser-portable"
!endif

!define APP_NAME      "FpBrowser"
!define APP_DISPLAY   "FpBrowser 指纹浏览器"
!define APP_VERSION   "1.0.0"
!define APP_PUBLISHER "FpBrowser"
!define APP_EXE       "FpBrowser.exe"
!define UNINST_KEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

Unicode true
SetCompressor /SOLID lzma

Name "${APP_DISPLAY}"
OutFile "/root/downloads/FpBrowser-Setup.exe"
InstallDir "$LOCALAPPDATA\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel user
ShowInstDetails show
ShowUninstDetails show

;--------------------------------
; UI
!include "MUI2.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON   "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即启动 ${APP_DISPLAY}"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

;--------------------------------
; 安装
Section "Install" SecInstall
  SetOutPath "$INSTDIR"

  File "${SRCDIR}\${APP_EXE}"
  File "${SRCDIR}\main.py"
  File "${SRCDIR}\fingerprint.py"
  File "${SRCDIR}\chrome_setup.py"
  File "${SRCDIR}\migrate.py"
  File "${SRCDIR}\使用说明.txt"
  File "${SRCDIR}\启动.bat"
  File "${SRCDIR}\启动-调试.bat"

  ; 整个 python\ 目录 (含 tcl/, DLLs/, Lib/site-packages/, python.exe, pythonw.exe)
  File /r "${SRCDIR}\python"

  ; 桌面快捷方式
  CreateShortCut "$DESKTOP\${APP_DISPLAY}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0

  ; 开始菜单
  CreateDirectory "$SMPROGRAMS\${APP_DISPLAY}"
  CreateShortCut "$SMPROGRAMS\${APP_DISPLAY}\${APP_DISPLAY}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortCut "$SMPROGRAMS\${APP_DISPLAY}\卸载 ${APP_DISPLAY}.lnk" "$INSTDIR\uninstall.exe"

  ; 卸载器
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; 写注册表 (控制面板里能看到, 能从那里卸载)
  WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName"     "${APP_DISPLAY}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

;--------------------------------
; 卸载
Section "Uninstall"
  ; 注意: 用户的窗口配置在 %LOCALAPPDATA%\FpBrowser\config.json
  ; 但安装目录恰好也是 %LOCALAPPDATA%\FpBrowser, 所以删之前先备份配置
  IfFileExists "$INSTDIR\config.json" 0 +2
    CopyFiles /SILENT "$INSTDIR\config.json" "$LOCALAPPDATA\${APP_NAME}-config-backup.json"

  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\main.py"
  Delete "$INSTDIR\fingerprint.py"
  Delete "$INSTDIR\chrome_setup.py"
  Delete "$INSTDIR\migrate.py"
  Delete "$INSTDIR\使用说明.txt"
  Delete "$INSTDIR\启动.bat"
  Delete "$INSTDIR\启动-调试.bat"
  Delete "$INSTDIR\uninstall.exe"
  RMDir /r "$INSTDIR\python"
  ; 不删 profiles\, config.json — 用户数据保留
  ; 如果整个 $INSTDIR 空了再删
  RMDir "$INSTDIR"

  Delete "$DESKTOP\${APP_DISPLAY}.lnk"
  RMDir /r "$SMPROGRAMS\${APP_DISPLAY}"

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd
