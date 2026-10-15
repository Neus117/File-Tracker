"""读回可执行文件的**版本资源**并校验，供 `build.ps1` 第 4 步调用。

## 为什么是"读回产物"而不是"相信 spec"

spec 里把 `version=` 写对，**不等于** PyInstaller 真的把它写进了 exe。
这个项目刚因为同一类问题发过一次事故：`_build_info` 生成在错误的目录，
`--version` 一直自报 `unknown`，而构建全绿。

所以这里问的是"**它里面到底有什么**"，答案是读出来的才算。

用法::

    python tools/check_exe_version.py "dist/File Tracker.exe" 1.2.2

退出码 0 = 通过；非 0 = 不通过（原因打到 stderr）。
"""

from __future__ import annotations

import re
import sys

# **输出必须先切成 UTF-8。**
#
# 版权字段里有 ``©``（U+00A9），而 Windows 控制台默认是 GBK——
# 实测直接 print 会死在
# ``UnicodeEncodeError: 'gbk' codec can't encode character '\xa9'``，
# 于是**检查本身失败**，看起来像"版本资源有问题"。
#
# 调用方（`build.ps1`）已经带了 `-X utf8`，但那是调用方的责任；
# 一个被单独运行的脚本不该因为没带那个开关就崩。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):                 # 极老的 Python / 被重定向
    pass

#: 必须存在且非空的字段，以及它们在报告里的显示名。
REQUIRED = (
    ("FileDescription", "文件说明"),
    ("FileVersion", "文件版本"),
    ("ProductName", "产品名称"),
    ("ProductVersion", "产品版本"),
    ("LegalCopyright", "版权"),
)


def read_fields(exe_path: str) -> dict[str, str]:
    """把版本资源里的字符串字段读成一个字典。"""
    from PyInstaller.utils.win32.versioninfo import (
        read_version_info_from_executable,
    )

    raw = str(read_version_info_from_executable(exe_path))
    fields: dict[str, str] = {}
    for key, _label in REQUIRED:
        found = re.search(rf"StringStruct\('{key}', (.*?)\)", raw)
        fields[key] = found.group(1).strip("'") if found else ""
    return fields


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法: check_exe_version.py <exe> <期望的产品版本>",
              file=sys.stderr)
        return 2

    exe_path, expected = argv
    try:
        fields = read_fields(exe_path)
    except Exception as error:                       # noqa: BLE001
        print(f"读不出版本资源：{type(error).__name__}: {error}",
              file=sys.stderr)
        return 1

    problems = []
    for key, label in REQUIRED:
        if not fields[key]:
            problems.append(f"{label}（{key}）是空的")
    # **产品版本必须与本次构建一致**，否则属性页会骗人。
    if fields["ProductVersion"] and fields["ProductVersion"] != expected:
        problems.append(
            f"产品版本是 {fields['ProductVersion']}，"
            f"与本次构建的 {expected} 不一致")
    # 提交哈希**不该**出现在属性页（理由见 tools/version_info.py）。
    if "+" in fields.get("ProductVersion", ""):
        problems.append(
            f"产品版本里带了提交哈希（{fields['ProductVersion']}）——"
            "哈希只该出现在 --version 的输出里")

    print("  ".join(f"{label}={fields[key]}"
                    for key, label in REQUIRED))
    if problems:
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
