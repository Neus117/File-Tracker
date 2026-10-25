"""核对文档的两类**结构性**缺陷：中英 README 漂移、release 说明里出现重复段。

## 一、中英两版 README 必须同步

用户的要求是"**正确**添加未同步/缺失的英文版描述" —— 关键在"正确"。
两份 README 最容易出的问题是**悄悄漂移**：
一边改了数字，另一边忘了；或者少了一节、多了一节。

**"我对照着写了一遍"不是证据。** 所以这里逐项比：

* **节标题**：数量与顺序必须一一对应
* **数字**：两份里出现的同一批关键数字必须相同
* **切换链接**：两边都要有，且指向对方

## 二、`notes/*.md`（release 说明的本地正本）里不能有重复段

**这一条是补上的**：v1.2.5 的说明一度出现**两个 `**English**` 标题**
—— 第一轮改写破例给它手写了一个英文块，第二轮"给 v1.2.x 补英文"的脚本
又追加了一个，于是同一份里并排躺着两块。

**成因是"分两轮改同一份文档、后一轮不知道前一轮做过什么"。**
判据很简单也很硬：每份说明里

* **恰好一个**一级标题
* **至多一个** `**English**` 块
* **恰好一条**指向双语 README 的入口
"""
import io
import os
import re

#: **仓库根由脚本位置推出来，不要写死绝对路径。**
#: 写死的话本机能跑、CI 上必然找不到文件——而那正是"本机能过"骗人的经典形状。
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZH = os.path.join(REPO, "README.md")
EN = os.path.join(REPO, "README.en.md")


def sections(path: str) -> list[str]:
    text = io.open(path, encoding="utf-8").read()
    return [m.group(1).strip() for m in re.finditer(r"^## (.+)$", text, re.M)]


def main() -> int:
    zh = io.open(ZH, encoding="utf-8").read()
    en = io.open(EN, encoding="utf-8").read()
    ok = True

    print("=== ① 节标题一一对应 ===")
    zs, es = sections(ZH), sections(EN)
    print(f"  中文 {len(zs)} 节｜英文 {len(es)} 节")
    if len(zs) != len(es):
        print("  ❌ 节数不同")
        ok = False
    for i, (a, b) in enumerate(zip(zs, es), 1):
        print(f"    {i}. {a:<28} | {b}")

    print()
    print("=== ② 关键数字两份是否一致 ===")
    # ## 这些 pattern 是**当前版本的实际值**，每次发版都要跟着改
    #
    # 它们不是"历史记录"—— 判据是"两份 README 里都出现同一个当前值"。
    # 改了 README 却忘了改这里，门禁会报"某一份缺失"，那是**提示你同步**，
    # 不是误报。
    #
    # 测试数用带单位的 pattern（`200 条单元测试`）而不是裸数字 `200`：
    # 裸数字会命中 `3000`、`1200` 这类无关内容，判据就失去意义了。
    facts = [
        ("版本号", "v1.4.2"),
        ("体积", r"12\.73 MB"),
        ("旧体积", r"15\.76 MB"),
        ("单元测试", "220 条单元测试|220 unit tests"),
        ("界面检查", "256 项界面检查|256 GUI checks"),
        ("门禁数", r"9 道门禁|9 gates"),
        ("审计判据", r"50 条判据|50 criteria"),
        ("排序条目数", r"3000"),
    ]
    for label, pattern in facts:
        a = bool(re.search(pattern, zh))
        b = bool(re.search(pattern, en))
        mark = "✅" if (a and b) else ("❌" if a != b else "⚠️")
        if not (a and b):
            ok = False
        print(f"    {mark} {label:<10} 中文={a}  英文={b}")

    print()
    print("=== ③ 切换链接 ===")
    # **不要写死标签文字。** 第一版查的是 `"简体中文](README.md)"`，
    # 而实际写的是 `[**简体中文**](README.md)`（标签里带加粗），于是**误报断链**。
    # 改成解析 markdown 链接本身，只看"目标指向谁"。
    def md_links(text: str) -> list[tuple[str, str]]:
        return [(m.group(1), m.group(2))
                for m in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", text)]

    zh_links = md_links(zh)
    en_links = md_links(en)
    zh_ok = any(t == "README.en.md" for _l, t in zh_links)
    en_ok = any(t == "README.md" for _l, t in en_links)
    # 还必须**自指**（切回自己那一版），否则只有单向
    zh_self = any(t == "README.md" for _l, t in zh_links)
    en_self = any(t == "README.en.md" for _l, t in en_links)
    print(f"    {'✅' if zh_ok else '❌'} 中文版指向 README.en.md")
    print(f"    {'✅' if en_ok else '❌'} 英文版指向 README.md")
    print(f"    {'✅' if zh_self else '❌'} 中文版自指 README.md")
    print(f"    {'✅' if en_self else '❌'} 英文版自指 README.en.md")
    ok = ok and zh_ok and en_ok and zh_self and en_self

    print()
    print("=== ④ 是否残留过期数字（155 / 44 条判据）===")
    stale = []
    # ⚠️ **`186` 不再按"数字本身"判过期。**
    #
    # 它当初是**旧的单元测试数**，所以被列入过期清单（`\b186\b`）。
    # 但从 v1.3.0 起，186 是**正确的界面检查数** ——
    # 继续按数字全匹配，会把**正确的新数字**判成过期。
    # ⇒ 只抓真正的那种误用写法："186 条单元测试"（186 在『单元测试』前面）。
    for pat, what in [(r"186\s*条\s*单元测试", "单元测试 186（旧写法）"),
                      (r"44 条判据", "审计判据 44")]:
        for name, text in (("中文", zh), ("英文", en)):
            if re.search(pat, text):
                stale.append(f"{name}版 {what}")
    if stale:
        print(f"    ❌ 残留：{stale}")
        ok = False
    else:
        print("    ✅ 无残留")

    print()
    print("=== ⑤ 行数 ===")
    print(f"    中文 {len(zh.splitlines())} 行｜英文 {len(en.splitlines())} 行")

    print()
    print("=== ⑥ notes/*.md（release 说明的正本）结构 ===")
    notes_dir = os.path.join(REPO, "notes")
    if not os.path.isdir(notes_dir):
        print("    ⚠️ 没有 notes/ 目录，跳过")
    else:
        names = sorted(n for n in os.listdir(notes_dir) if n.endswith(".md"))
        print(f"    {'文件':<14}{'一级标题':>9}{'English':>9}{'README入口':>11}")
        for name in names:
            text = io.open(os.path.join(notes_dir, name),
                           encoding="utf-8").read()
            h1 = len(re.findall(r"^# ", text, re.M))
            en_blocks = len(re.findall(r"^\*\*English\*\*$", text, re.M))
            links = text.count("README](https://")
            bad = h1 != 1 or en_blocks > 1 or links != 1
            if bad:
                ok = False
            print(f"    {name:<14}{h1:>9}{en_blocks:>9}{links:>11}"
                  f"{'   ❌' if bad else ''}")
        print("    判据：一级标题恰好 1、English 块至多 1、README 入口恰好 1")

    print()
    print("  ✅ 全部一致" if ok else "  ❌ 有不一致项，见上")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
