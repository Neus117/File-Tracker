r"""验证"一个程序能不能起来" —— **自带硬超时、超时杀进程树、按进程树找窗口**。

## 这份文件修过两次，两次都是**检测方法的错**，不是程序的错

### 第一次（用户指出，2026-10-17）

> "每个测试环节一定要加超时控制机制……它总是会一直卡住思考 10 分钟、
> 20 分钟甚至半个小时，直到我手动干预把窗口关掉。"

当时的问题：没有整体超时 + `terminate()` 只杀直接子进程（onefile 有子进程，
窗口一直挂着）+ 用 `MainWindowTitle` 判窗口（`-WindowStyle Hidden` 时恒为空）。

### 第二次（用户用截图指出，同一天）

我给 exe 判了"60 秒无窗口 ⇒ 打包装坏了"，据此回退了 spec、删了 dist、
还写进文档说"exe 起不来"。

**用户发来截图：程序窗口正常显示、数据完整。**

真正的原因：

```text
PyInstaller --onefile 是**两层进程**：
    父进程（bootloader）→ 解压到 %TEMP% → 启动**子进程**（真正的程序）
                                  ↑ 窗口属于它
subprocess.Popen 拿到的 proc.pid 是**父进程**
⇒ windows_of(proc.pid) 永远是个空列表
```

**内核级的证据**：`--version` / `--selftest` 都正常（父进程把参数转给子进程，
子进程打印后退出）；进程"存活"没窗口（父进程在等子进程）；内存只 8.9 MB
（那只是 bootloader 自己）。

## 现在的做法

* **按进程树**找窗口：先 `descendant_pids(root)`，再逐个 `windows_of(pid)`
* **`finally` 里 `taskkill /F /T`** —— `/T` 真的杀掉子进程
* 单对象超时 ≤ `DEFAULT_TIMEOUT`（60 秒），整体 ≤ 3 分钟
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

DEFAULT_TIMEOUT = 60

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


def descendant_pids(root_pid: int) -> list[int]:
    """`root_pid` 的**所有后代**（含自己）。

    ## 为什么必须要有这一层

    PyInstaller `--onefile` 的窗口属于**子进程**，不属于 `Popen` 拿到的那个
    bootloader。只查 `proc.pid` 会得出"没窗口"的错误结论（我踩过，
    还据此误判"打包坏了"，回退了本没问题的改动）。

    用 `CreateToolhelp32Snapshot` 枚举全表、按 `th32ParentProcessID` 建树，
    比调 `wmic` 快且不依赖外部命令。
    """
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == -1:
        return [root_pid]
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        parent_of: dict[int, int] = {}
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parent_of[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)

    children: dict[int, list[int]] = {}
    for pid, parent in parent_of.items():
        children.setdefault(parent, []).append(pid)

    result, queue = [], [root_pid]
    while queue:
        current = queue.pop()
        if current in result:
            continue
        result.append(current)
        queue.extend(children.get(current, []))
    return result


def windows_of(pid: int) -> list[str]:
    """该进程**可见且有标题**的顶层窗口标题。

    **不看 `MainWindowTitle`**：它是进程自己的属性，对某些进程恒为空，
    而 `Start-Process -WindowStyle Hidden` 启动的进程更是永远读不到。
    """
    found: list[str] = []

    def callback(hwnd, _lparam):
        owner = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and _user32.IsWindowVisible(hwnd):
            length = _user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buffer, length + 1)
                found.append(buffer.value)
        return True

    _user32.EnumWindows(_EnumWindowsProc(callback), 0)
    return found


def windows_in_tree(root_pid: int) -> list[str]:
    """**整棵进程树**里的可见窗口（onefile 的窗口在子进程上）。"""
    titles: list[str] = []
    for pid in descendant_pids(root_pid):
        titles.extend(windows_of(pid))
    return titles


def kill_tree(pid: int) -> None:
    """按进程树强杀。`/T` 是关键 —— 少它就是"父进程死了、窗口还开着"。"""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def probe_launch(cmd: list[str], label: str, timeout: int = DEFAULT_TIMEOUT):
    """起一个程序，`timeout` 秒内**进程树里出现窗口**算成功。无论如何都杀干净。"""
    print("── %s ──" % label)
    print("   命令: %s" % " ".join(cmd))
    started = time.monotonic()
    try:
        proc = subprocess.Popen(cmd)
    except OSError as error:
        return False, "启动失败: %s" % error

    print("   pid = %d，超时上限 %d 秒" % (proc.pid, timeout))
    deadline = started + timeout
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return False, "进程退出（码 %s）" % proc.returncode
            titles = windows_in_tree(proc.pid)
            if titles:
                elapsed = time.monotonic() - started
                return True, "第 %.1f 秒出现窗口 %r" % (elapsed, titles)
            time.sleep(0.5)
        return False, "%d 秒内进程树中无可见窗口" % timeout
    finally:
        kill_tree(proc.pid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", action="store_true",
                        help="测 dist 里打包好的 exe（默认测源码）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="单个对象的超时秒数（默认 %d）" % DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if args.exe:
        target = os.path.join(root, "dist", "File Tracker.exe")
        label, cmd = "打包产物 dist/File Tracker.exe", [target]
    else:
        target = os.path.join(root, "src", "main.py")
        label, cmd = "源码 src/main.py", [sys.executable, "-X", "utf8", target]

    if not os.path.exists(target):
        print("找不到目标: %s" % target)
        return 2

    ok, detail = probe_launch(cmd, label, timeout=args.timeout)
    print("   结论: %s —— %s" % ("✅ 通过" if ok else "❌ 失败", detail))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
