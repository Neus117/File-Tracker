"""审计：`libcrypto-3-x64.dll`（2.11 MB）到底是谁拉进产物的。

## 为什么要查这个

它是归档里第二大的东西（仅次于 wx 的 core DLL 和 python311.dll），
而应用源码里**根本没有** `ssl` / `hashlib` / `http` / `urllib` / `socket`。

`libcrypto` 通常由 `_hashlib` 或 `_ssl` 带进来。逐个排除，找出真正的调用者。

判据：分别单独导入每一个可疑模块，看谁会让 `_hashlib` 出现。
"""
from __future__ import annotations

import subprocess
import sys

CANDIDATES = [
    "sqlite3", "wx", "json", "tempfile", "subprocess", "winreg",
    "ctypes", "urllib.request", "email", "http.client", "socket",
    "hashlib", "ssl", "random", "secrets", "uuid", "platform",
    "logging", "argparse", "shutil", "zipfile", "tarfile", "statistics",
    "getpass", "mimetypes", "pydoc", "pdb", "traceback", "pickle",
]

PROBE = (
    "import sys; before=set(sys.modules); import {mod};"
    "pulled=sorted(m for m in set(sys.modules)-before"
    " if m.split('.')[0] in {{'_hashlib','hashlib','ssl','_ssl',"
    "'socket','_socket','select','selectors'}});"
    "print('{mod}|' + ','.join(pulled))"
)


def run(module: str) -> str:
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", PROBE.format(mod=module)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (result.stdout or "").strip()
    if out:
        return out.split("|", 1)[1]
    err = (result.stderr or "").strip().splitlines()
    return f"(导入失败) {err[-1] if err else '无输出'}"


print("  模块                  它拉进来的加密/网络相关模块")
print("  " + "-" * 62)
blamed: list[str] = []
for module in CANDIDATES:
    pulled = run(module)
    if pulled and not pulled.startswith("("):
        blamed.append((module, pulled))
        print(f"  {module:20} {pulled}")
print()
if blamed:
    print("  **会拉进加密/网络模块的：**")
    for module, pulled in blamed:
        print(f"    {module:20} → {pulled}")
else:
    print("  以上候选**都不会**拉进 _hashlib / _ssl / libcrypto。")
    print("  说明它是 PyInstaller 的某个 hook 静态收集的，不是运行时导入。")

print()
print("  === 换个角度：本机 ft_env 里 _hashlib 依赖哪个 DLL ===")
result = subprocess.run(
    [sys.executable, "-X", "utf8", "-c",
     "import _hashlib, os;"
     "print('_hashlib 文件:', _hashlib.__file__)"],
    capture_output=True, text=True, encoding="utf-8", errors="replace")
print("    " + ((result.stdout or "").strip() or (result.stderr or "").strip()))

print()
print("  === PyInstaller 的 hook 里有没有提到 libcrypto / _hashlib ===")
import glob
import os

import PyInstaller

hooks_dir = os.path.join(os.path.dirname(PyInstaller.__file__), "hooks")
hits = []
for path in glob.glob(os.path.join(hooks_dir, "**", "*.py"), recursive=True):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    if "_hashlib" in text or "libcrypto" in text:
        hits.append(os.path.relpath(path, hooks_dir))
for name in sorted(hits):
    print(f"    {name}")
if not hits:
    print("    （没有 hook 提到它们）")
