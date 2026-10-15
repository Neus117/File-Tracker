"""临时工具：核对 docs/调色与排版-改哪里.md 里所有"第 N 行"引用。

文档里的行号会随代码改动漂移，所以每次改完都跑一遍这个。
"""
import io
import os
import re

REPO = r"D:\Coding\MyGitHub\File-Tracker"
DOC = os.path.join(REPO, "docs", "调色与排版-改哪里.md")

FILES = {
    "app.py": "src/file_tracker/app.py",
    "theme.py": "src/file_tracker/theme.py",
    "widgets.py": "src/file_tracker/widgets.py",
    "header.py": "src/file_tracker/header.py",
    "win32.py": "src/file_tracker/win32.py",
}

cache = {
    key: io.open(os.path.join(REPO, rel.replace("/", os.sep)),
                 encoding="utf-8").read().splitlines()
    for key, rel in FILES.items()
}

doc = io.open(DOC, encoding="utf-8").read()
found = 0
for match in re.finditer(r"第 \*\*(\d+)\*\* 行", doc):
    number = int(match.group(1))
    context = doc[max(0, match.start() - 200):match.end() + 60]
    for key in FILES:
        if key not in context:
            continue
        lines = cache[key]
        actual = lines[number - 1].strip() if number <= len(lines) else "<越界>"
        print(f"  {key}:{number}  {actual[:68]}")
        found += 1
        break

print()
print(f"共 {found} 处带文件名的行号引用（以上都需要人工扫一眼是否对得上）")
