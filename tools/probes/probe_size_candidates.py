"""审计：体积优化的**可量化**候选，逐项验证。

不用"名字看起来多余"这种判断——每一项都给出：
  ① 它是什么、多大
  ② 谁把它拉进来的（证据）
  ③ 排掉它的风险

只保留能说清"谁需要它"的项；说不清的一律列为"不确定，需实测"。
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, "src")

EXE = os.path.join("dist", "File Tracker.exe")


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


# --------------------------------------------------------------------------
section("① 未被引用的资源文件（可直接不打包）")
# --------------------------------------------------------------------------
images_dir = os.path.join("images")
used_names: set[str] = set()
import ast  # noqa: E402

for name in sorted(os.listdir(os.path.join("src", "file_tracker"))):
    if not name.endswith(".py"):
        continue
    source = open(os.path.join("src", "file_tracker", name),
                  encoding="utf-8").read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            used_names.add(os.path.basename(node.value))

print(f"  {'文件':44} {'大小':>12}  被引用?")
unused_total = 0
for name in sorted(os.listdir(images_dir)):
    path = os.path.join(images_dir, name)
    if not os.path.isfile(path):
        continue
    size = os.path.getsize(path)
    used = name in used_names
    if not used:
        unused_total += size
    print(f"  {name:44} {size:12,d}  {'是' if used else '**否**'}")
print(f"\n  未被引用的合计 {unused_total:,d} B ({unused_total / 1024:.1f} KB)")
print("  `datas` 打的是**整个 images 目录**，所以这些会原样进产物。")

# --------------------------------------------------------------------------
section("② libcrypto / _hashlib：谁把它拉进来的")
# --------------------------------------------------------------------------
print("  应用源码里的 import 顶层名：")
found: set[str] = set()
for name in sorted(os.listdir(os.path.join("src", "file_tracker"))):
    if not name.endswith(".py"):
        continue
    tree = ast.parse(open(os.path.join("src", "file_tracker", name),
                          encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
print(f"    {' '.join(sorted(found))}")
print()
print("  其中有没有 ssl / hashlib / http / urllib / socket？")
for suspect in ("ssl", "hashlib", "http", "urllib", "socket", "select"):
    print(f"    {suspect:10} {'**有**' if suspect in found else '没有'}")
print()
def run_probe(code: str) -> str:
    """跑一段探针代码并拿到 stdout。

    **必须显式给编码。** 踩过：不给的话 `subprocess` 用系统默认
    （本机 GBK）去解码，而 Python 输出的是 UTF-8 中文，
    于是 `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc0`
    ——而且它发生在**读取线程**里，主线程只看到 `stdout` 是 `None`。
    """
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    return out if out else (f"(失败) {err.splitlines()[-1] if err else '无输出'}")


print("  实测：单独导入 sqlite3 会不会拉进 _hashlib / libcrypto")
print("    " + run_probe(
    "import sys; before=set(sys.modules); import sqlite3;"
    "print('sqlite3 拉进:', sorted(m for m in set(sys.modules)-before"
    " if m.split('.')[0] in {'_hashlib','hashlib','ssl','_ssl','socket',"
    "'select','selectors','_socket','_decimal','decimal','_lzma','lzma',"
    "'_bz2','bz2','unicodedata'}))"))

print()
print("  实测：导入 wx 之后会不会拉进这些")
print("    " + run_probe(
    "import sys; before=set(sys.modules); import wx;"
    "print('wx 拉进:', sorted(m for m in set(sys.modules)-before"
    " if m.split('.')[0] in {'_hashlib','hashlib','ssl','_ssl','socket',"
    "'select','selectors','_socket','_decimal','decimal','_lzma','lzma',"
    "'_bz2','bz2','unicodedata','email','urllib','http'}))"))
