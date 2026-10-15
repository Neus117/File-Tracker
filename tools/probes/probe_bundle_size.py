"""审计：产物里到底打进了什么。

读 PyInstaller 的 CArchive（exe 里的那一段），列出每一项的大小，
并按"看起来多余"分类——不是猜，是列出实际存在的东西。
"""
import os
import sys

from PyInstaller.archive.readers import CArchiveReader

EXE = os.path.join("dist", "File Tracker.exe")

#: 这些名字出现在归档里通常意味着"某个库被连带打进来了"
SUSPECT = ("ssl", "crypto", "hashlib", "unittest", "email", "http", "urllib",
           "xml", "pydoc", "lib2to3", "distutils", "setuptools", "pip",
           "tk", "tcl", "numpy", "pil", "pytest", "test")


def size_of(entry) -> int:
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        return entry[1] if isinstance(entry[1], int) else 0
    return 0


reader = CArchiveReader(EXE)
rows = [(name, size_of(reader.toc[name])) for name in reader.toc]
total = sum(s for _n, s in rows)
on_disk = os.path.getsize(EXE)

print(f"  exe 磁盘大小        {on_disk:12,d} B  ({on_disk / 1024 / 1024:.2f} MB)")
print(f"  归档内解压后合计    {total:12,d} B  ({total / 1024 / 1024:.2f} MB)")
print(f"  归档项数            {len(rows)}")
print()

print("=== ① wx 相关（必需，但可以看看有没有用不到的模块）===")
wx_rows = sorted(((n, s) for n, s in rows if n.lower().startswith("wx")),
                 key=lambda kv: -kv[1])
wx_total = sum(s for _n, s in wx_rows)
print(f"  小计 {wx_total / 1024 / 1024:.2f} MB，共 {len(wx_rows)} 项")
for name, size in wx_rows:
    print(f"    {size / 1024 / 1024:7.2f} MB  {name}")
print()

print("=== ② 名字可疑的（可能被连带打进来）===")
hits = [(n, s) for n, s in rows
        if any(k in n.lower() for k in SUSPECT)]
hits.sort(key=lambda kv: -kv[1])
if hits:
    for name, size in hits:
        print(f"    {size / 1024 / 1024:7.2f} MB  {name}")
    print(f"  小计 {sum(s for _n, s in hits) / 1024 / 1024:.2f} MB")
else:
    print("  无")

print()
print("=== ③ images\\ 里打进去的 ===")
img = sorted(((n, s) for n, s in rows if "images" in n.lower()),
             key=lambda kv: -kv[1])
for name, size in img:
    print(f"    {size:10,d} B  {name}")
print(f"  小计 {sum(s for _n, s in img) / 1024:.1f} KB")
print()

print("=== ④ 全部非 wx 项（按大小，前 30）===")
rest = sorted(((n, s) for n, s in rows if not n.lower().startswith("wx")),
              key=lambda kv: -kv[1])
for name, size in rest[:30]:
    print(f"    {size / 1024 / 1024:7.2f} MB  {name}")
