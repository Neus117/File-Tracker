"""诊断：PyInstaller 的版本资源 API 怎么用、写出来的 exe 属性对不对。

对照 Roboc 的 `Directory.Build.props`，它给 exe 设了这些字段
（Explorer「属性 → 详细信息」看到的就是它们）：

    FileDescription   Roboc - fast copy and delete for Windows
    FileVersion       1.0.6.0
    ProductName       Roboc
    ProductVersion    1.0.6
    LegalCopyright    Copyright © 2026 Neus117
    Language          语言中性

本项目要照做。这个探针只回答"API 怎么调、能不能读回来"，
真正的实现在 `tools/version_info.py`。
"""
import os
import subprocess
import sys

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
    write_version_info_to_executable,
)

OUT = os.path.join(os.environ.get("TEMP", "."), "verinfo-probe.txt")


def file_version(version: str) -> tuple:
    """``"1.2.2"`` → ``(1, 2, 2, 0)``。四段，缺的补 0。"""
    parts = []
    for chunk in version.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
        if len(parts) == 4:
            break
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


print("=== file_version 解析 ===")
for raw in ("1.2.2", "1.2.1", "1.0.6", "2", "1.2.3.4"):
    print(f"  {raw!r:12} → {file_version(raw)}")

info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=file_version("1.2.2"),
        prodvers=file_version("1.2.2"),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", "Neus117"),
                StringStruct("FileDescription",
                             "File Tracker - folder access tracker for Windows"),
                StringStruct("FileVersion", "1.2.2.0"),
                StringStruct("InternalName", "File Tracker"),
                StringStruct("LegalCopyright", "Copyright \u00a9 2026 Neus117"),
                StringStruct("OriginalFilename", "File Tracker.exe"),
                StringStruct("ProductName", "File Tracker"),
                StringStruct("ProductVersion", "1.2.2"),
            ]),
        ]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

print()
print("=== 生成的资源结构 ===")
print(info)
with open(OUT, "w", encoding="utf-8") as handle:
    handle.write(str(info))
print(f"  也已写到 {OUT}（PyInstaller 的 spec 就是读这样一个文本文件）")
