r"""验：**排序/顶置之后，选中必须还在原来那条记录上**（不许错位到隔壁）。

## 这是审计实测出来的 bug（2026-10-17）

`_render_rows` 里恢复选中时，原来是这样取的：

```python
keep_paths = self._selected_paths()      # ← 内部用 self._rows[index]
```

而 `index` 是**控件的行号**。`sort_list_items` 的顺序是：

```
3243:  self._remember_view()          # _rows 还是旧的
3244:  self._rows = pinned + unpinned  # ← 这里换了表
3245:  self._render_rows()            # ← 再用旧行号查新表 ⇒ **错位**
```

**顶置**是最好复现的场景：那条记录被挪到第 0 行，
于是"原来第 166 行"在新表里是**另一条记录**（原来第 167 行那条）。

实测读数：`顶置前 sel=166 dir-0166` → `顶置后 sel=166 **dir-0165**`。

**后果不只是高亮在错的位置** —— 之后右键「删除」删的是**隔壁那条**（不可逆）。

## 判据

| # | 判据 |
|---|---|
| 1 | 顶置之后，**选中那条的路径 = 被顶置的那条** |
| 2 | 按"访问日期"排序后打开一条，选中 = 打开的那条 |
| 3 | 取消置顶后，选中仍是被操作的那条 |
| 4 | 阳性对照：操作前选中**确实在**那条上（否则 1-3 是假通过） |
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def pump(rounds=20, pause=0.005):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def select_only(frame, row):
    control = frame.list_ctrl
    for index in range(control.GetItemCount()):
        control.Select(index, index == row)
    if 0 <= row < control.GetItemCount():
        control.Focus(row)
    pump(8)


with probe_temp("probe-selection-drift") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(200):
        seed.record_access(os.path.join(scratch, "dir-%04d" % i))
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)
    ctrl = frame.list_ctrl

    try:
        # ══ 场景 1：顶置一条靠下的记录 ══════════════════════════
        victim_row = 166
        victim_path = frame.row_path(victim_row)
        neighbour_path = frame.row_path(victim_row + 1)
        select_only(frame, victim_row)
        pump(10)
        before = frame.selected_paths()
        print("【顶置】")
        print("  操作前：选中行 = %d  路径 = …%s" % (victim_row, victim_path[-22:]))
        check("4 阳性对照：顶置前选中确实在那条上",
              before == [victim_path],
              "选中 = %s" % [p[-14:] for p in before])

        frame.on_pin(None)          # = 右键「顶置」
        pump(30)
        after = frame.selected_paths()
        print("  顶置后：选中 = %s" % [p[-14:] for p in after])
        print("         （期望 …%s；隔壁那条是 …%s）"
              % (victim_path[-14:], neighbour_path[-14:]))
        check("1 顶置后选中**仍是那条被顶置的记录**",
              after == [victim_path],
              "选中 = %s，期望 = %s，隔壁 = %s"
              % ([p[-14:] for p in after], victim_path[-14:], neighbour_path[-14:]))

        # ══ 场景 2：取消置顶（同样会重排）══════════════════════
        frame.on_unpin(None)
        pump(30)
        after_unpin = frame.selected_paths()
        print("\n【取消置顶】")
        print("  取消后：选中 = %s" % [p[-14:] for p in after_unpin])
        check("3 取消置顶后选中**仍是那条**",
              after_unpin == [victim_path],
              "选中 = %s" % [p[-14:] for p in after_unpin])

        # ══ 场景 3：按"访问时间"排序（顺序会变）后打开一条 ═════
        print("\n【按访问时间排序后打开一条】")
        frame.sort_reverse = True
        frame.sort_list_items(app_mod.COLUMN_TIME)
        pump(30)
        target_row = 80
        target_path = frame.row_path(target_row)
        select_only(frame, target_row)
        pump(10)
        picked = frame.selected_paths()
        frame._focus_pane = "list"
        frame.open_folder = open_in_explorer_stub()
        frame.record_accessed_path(target_path)   # = 双击打开
        pump(40)
        after_open = frame.selected_paths()
        print("  打开 …%s" % target_path[-22:])
        print("  打开后：选中 = %s" % [p[-14:] for p in after_open])
        check("2 按时间排序后打开一条 ⇒ 选中**是刚打开的那条**",
              after_open == [target_path],
              "选中 = %s，期望 = %s"
              % ([p[-14:] for p in after_open], target_path[-14:]))
        check("2b 阳性对照：打开前选中的确实是它",
              picked == [target_path],
              "选中 = %s" % [p[-14:] for p in picked])
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print("  %s %s" % ("OK  " if ok else "FAIL", name))
    if detail:
        print("       %s" % detail)
print()
print("  合计 %d 条：%d 通过，%d 失败" % (len(results), passed, len(results) - passed))
