package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
)

func main() {
	exe, err := os.Executable()
	if err != nil {
		os.Exit(1)
	}
	dir := filepath.Dir(exe)
	py := filepath.Join(dir, "python", "pythonw.exe")
	script := filepath.Join(dir, "main.py")

	cmd := exec.Command(py, script)
	cmd.Dir = dir
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: 0x00000008 | 0x00000200, // DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
		HideWindow:    true,
	}
	if err := cmd.Start(); err != nil {
		os.Exit(2)
	}
}
