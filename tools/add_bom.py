"""给 .ps1 文件补上 UTF-8 BOM。

**Windows PowerShell 5.1 读没有 BOM 的 UTF-8 文件时会按 ANSI 解码**，
于是脚本里的中文变成乱码，甚至把字符串终止符吃掉导致语法错误。
本项目只用 5.1（这台机器上没有 PowerShell 7），所以每个 .ps1 都必须是
UTF-8 **带 BOM**。

用法::

    python tools/add_bom.py            # 处理仓库里所有 .ps1
    python tools/add_bom.py --check    # 只检查，不修改；有缺失则返回 1
"""

from __future__ import annotations

import argparse
import os
import sys

BOM = b"\xef\xbb\xbf"


def script_files(root: str) -> list[str]:
    found: list[str] = []
    for directory, _, files in os.walk(root):
        if ".git" in directory.split(os.sep):
            continue
        for name in files:
            if name.lower().endswith(".ps1"):
                found.append(os.path.join(directory, name))
    return sorted(found)


def has_bom(path: str) -> bool:
    with open(path, "rb") as handle:
        return handle.read(3) == BOM


def add_bom(path: str) -> None:
    with open(path, "rb") as handle:
        data = handle.read()
    if data.startswith(BOM):
        return
    with open(path, "wb") as handle:
        handle.write(BOM + data)


def main() -> int:
    parser = argparse.ArgumentParser(description="给 .ps1 补 UTF-8 BOM")
    parser.add_argument("--check", action="store_true", help="只检查，不修改")
    parser.add_argument("--root", default=None, help="仓库根目录")
    args = parser.parse_args()

    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = script_files(root)
    if not files:
        print("没找到 .ps1 文件", file=sys.stderr)
        return 1

    missing = []
    for path in files:
        relative = os.path.relpath(path, root)
        if has_bom(path):
            print(f"  [OK]   {relative}")
            continue
        if args.check:
            print(f"  [FAIL] {relative} 缺 UTF-8 BOM")
            missing.append(relative)
        else:
            add_bom(path)
            print(f"  [FIX]  {relative} 已补 BOM")

    if missing:
        print(
            f"\n{len(missing)} 个 .ps1 缺 BOM。"
            "Windows PowerShell 5.1 会把它们按 ANSI 解码，中文变乱码。",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
