"""生成 Windows 可执行文件的**版本资源**（就是「属性 → 详细信息」里那一页）。

## 为什么要有这个

对照 Roboc 的 `Directory.Build.props`，它给产物设了这些字段：

========================  ==================================================
字段                      值
========================  ==================================================
``FileDescription``       ``Roboc - fast copy and delete for Windows``
``FileVersion``           ``1.0.6.0``
``ProductName``           ``Roboc``
``ProductVersion``        ``1.0.6``
``LegalCopyright``        ``Copyright © 2026 Neus117``
``Language``              语言中性
========================  ==================================================

没有这一页的时候，资源管理器里看到的是一个**什么也没说**的 exe：
文件说明是空的、版权是空的。用户报障时也没法从属性里读出装的是哪一版。

## 一处刻意与 Roboc 不同

Roboc 的 csproj 里**没有** ``<Company>`` 之外的公司名字段，
``产品名称`` 那一行显示 "Roboc" 是 SDK 从程序集名推出来的。
这里显式写 ``ProductName``，不让它依赖推断——
推断规则换一次，显示就变一次。

## 一处**刻意相同**

**提交哈希不进版本资源。**

Roboc 的 csproj 里为这件事写了很长一段注释：SDK 会把
``+<sha>`` 追加到 ProductVersion 上，于是属性框里显示成
``1.0.0+51fc3bb8...`` ——"一个正确的事实，出现在错误的位置"。
哈希对报障有用，所以它留在 ``--version`` 的输出里，
**不进**资源管理器能看到的版本号。

本项目同样处理：``--version`` 打 ``File Tracker 1.2.2+<短哈希>``，
而属性页里只有干净的 ``1.2.2``。

## 语言

Roboc 选英文，理由写在它的注释里：

> A version resource carries one language, and this program speaks two.
> English is chosen because the string is read by anyone who opens the
> file's properties, including people who do not read Chinese.

本项目的界面语言是**跟随系统**的（见 :mod:`file_tracker.lang`），
但版本资源只有一格，所以同样选英文——理由与 Roboc 相同。
"""

from __future__ import annotations

#: 版本资源里的一律用英文（理由见模块文档"语言"一节）。
FILE_DESCRIPTION = "File Tracker - folder access tracker for Windows"

#: 与 Roboc 的字面量保持一致（同一作者、同一年份）。
COPYRIGHT = "Copyright \u00a9 2026 Neus117"

COMPANY = "Neus117"
PRODUCT_NAME = "File Tracker"
INTERNAL_NAME = "File Tracker"
ORIGINAL_FILENAME = "File Tracker.exe"

#: 语言与代码页：美国英语 + Unicode。Roboc 那边显示为"语言中性"。
LANG_ID = 0x0409
CODEPAGE = 1200
STRING_TABLE_KEY = f"{LANG_ID:04X}{CODEPAGE:04X}"


def file_version_tuple(version: str) -> tuple[int, int, int, int]:
    """``"1.2.2"`` → ``(1, 2, 2, 0)``。**四段**，缺的补 0。

    Windows 的 ``FILEVERSION`` 是四个 16 位整数，**不能只有三段**——
    少了会写不进去。所以这里一定要补齐到四段。

    非数字的部分会被剔掉（``"1.2.2-rc1"`` → ``(1, 2, 2, 0)``），
    这样即使以后加上预发布后缀也不会让构建失败。
    """
    parts: list[int] = []
    for chunk in str(version).split("."):
        digits = "".join(char for char in chunk if char.isdigit())
        parts.append(int(digits) if digits else 0)
        if len(parts) == 4:
            break
    while len(parts) < 4:
        parts.append(0)
    return (parts[0], parts[1], parts[2], parts[3])


def build_version_info(version: str):
    """构造 PyInstaller 的 ``VSVersionInfo``。

    延迟导入 PyInstaller —— 它是**构建期**依赖，
    运行时（含 pytest 与打包后的 exe）不该要求它存在。
    """
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = file_version_tuple(version)
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=numbers,
            prodvers=numbers,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,        # NT
            fileType=0x1,      # 应用程序
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([
                StringTable(STRING_TABLE_KEY, [
                    StringStruct("CompanyName", COMPANY),
                    StringStruct("FileDescription", FILE_DESCRIPTION),
                    # 四段（1.2.2.0）——属性页的「文件版本」就是它
                    StringStruct("FileVersion",
                                 ".".join(str(n) for n in numbers)),
                    StringStruct("InternalName", INTERNAL_NAME),
                    StringStruct("LegalCopyright", COPYRIGHT),
                    StringStruct("OriginalFilename", ORIGINAL_FILENAME),
                    StringStruct("ProductName", PRODUCT_NAME),
                    # 三段（1.2.2）——属性页的「产品版本」就是它。
                    # **不带提交哈希**，理由见模块文档。
                    StringStruct("ProductVersion", str(version)),
                ]),
            ]),
            VarFileInfo([VarStruct("Translation", [LANG_ID, CODEPAGE])]),
        ],
    )
