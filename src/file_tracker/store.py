"""数据层：SQLite 访问，不 import wx。

从 `FileTracker` 里抽出来的原因有两个：

1. **可测**。原来这些 SQL 散在 70 个方法里，要验证"记一次访问频次 +1"必须先开一个窗口。
2. **修掉一个真实的静默失效**。原来 ``save_accessed_paths`` 在每次退出时
   ``DELETE`` 全表再从 ListCtrl 重新 ``INSERT``——这意味着"界面里的行"才是真相来源，
   任何只改数据库不改界面的操作都会被下一次退出覆盖掉。

   本模块提供 :meth:`PathStore.replace_all`，但它现在只由"整表迁移/清空"调用；
   正常退出走 :meth:`PathStore.close`，**不再重写整表**。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS paths (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE,
    access_count INTEGER DEFAULT 1,
    last_access_time TEXT,
    is_pinned INTEGER DEFAULT 0,
    -- 顶置顺序：**越大越靠前**。
    --
    -- 为什么要单独一列，而不是复用 `id`：
    -- `id` 是"首次访问的先后"，它与"顶置的先后"是**两件不相干的事**。
    -- 复用 `id` 的话，要么新顶置的排最后（用户报过：不符合直觉），
    -- 要么把老顶置项的顺序反过来。
    --
    -- 0 表示"没顶置"，或"这一行来自加这一列之前的老数据"
    -- （老数据由 `_migrate_add_pin_order()` 补齐）。
    pin_order INTEGER DEFAULT 0
)
"""

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_time_cell(text: str) -> str:
    """把 ``2026-10-17 14:43:27`` 变成列表里显示的 ``14:43   26-10-17``。

    ## 用户的要求（2026-10-17）

    > "时间和日期本身就是一类的东西，最开始就不应该分成两列。
    >   只保留'访问时间'这一列，把日期并进去。
    >   格式：`14:43   26-10-17`，时间和日期之间用**3 个空格**隔开，
    >   **秒数在用户界面隐藏掉**，后端计算排序就行了。"

    所以：

    * **秒隐藏**（`14:43`）—— 界面上每次刷新都在变的秒对"这是什么时候访问的"
      几乎没有信息量，而它占的宽度却能省下来
    * **两位年份**（`26-10-17`）—— 用户指定
    * **3 个空格**分隔 —— 用户指定（比任何单字符分隔符都更容易扫读，
      这是 2026-10-15 那次"日期与时间分不清"的最终解法）

    ## 排序**不受影响**

    排序用的是 `PathRecord.last_access_time` 的**完整字符串**
    （ISO 格式，字典序 == 时间序），与这里的显示格式无关。
    也就是说：**显示可以省、可以变，排序键不动。**

    ## 容错

    格式不对（旧版本数据库里的怪值）时**原样返回**，不抛异常、不丢整行。
    """
    if not text:
        return ""
    parts = str(text).split(" ", 1)
    if len(parts) != 2:
        return str(text)
    date_part, clock_part = parts
    # 秒：`14:43:27` → `14:43`（只取前两段）
    clock_bits = clock_part.split(":")
    clock = ":".join(clock_bits[:2]) if len(clock_bits) >= 2 else clock_part
    # 年份：`2026-10-17` → `26-10-17`
    date_bits = date_part.split("-")
    if len(date_bits) == 3 and len(date_bits[0]) == 4:
        date = "%s-%s-%s" % (date_bits[0][2:], date_bits[1], date_bits[2])
    else:
        date = date_part
    return "%s   %s" % (clock, date)


def split_timestamp(text: str) -> tuple[str, str]:
    """把 ``2026-10-15 13:01:17`` 拆成 ``("2026-10-15", "13:01:17")``。

    **为什么拆**：用户 2026-10-15 反馈"最后访问时间"里日期与时间的间隔不够，
    两者要容易区分。试过靠一个更醒目的分隔符，但同一个分隔符在两种字号下
    观感差别很大；拆成两列之后中间有真正的列间距，任何字号、任何 DPI 下
    都分得清。

    **容错优先**：格式不对时把整串放在日期列、时间列留空，
    而不是抛异常或丢掉整行——时间戳来自旧版本数据库，格式未必统一。

    :return: ``(日期, 时间)``
    """
    if not text:
        return ("", "")
    parts = str(text).split(" ", 1)
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (str(text), "")


@dataclass(frozen=True)
class PathRecord:
    """一条访问记录。"""

    path: str
    access_count: int
    last_access_time: str
    is_pinned: bool = False


def now_text() -> str:
    """当前时间的存储形式（``%Y-%m-%d %H:%M:%S``，本地时区）。"""
    return datetime.now().strftime(TIME_FORMAT)


class PathStore:
    """`paths` 表的全部读写入口。

    刻意**不做**路径规范化——规范化是 :mod:`file_tracker.core` 的职责，
    调用方在进来之前就该把路径整理好。数据层保持"存什么读什么"。
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self.cursor.execute(SCHEMA)
        self.conn.commit()
        self._migrate_add_pin_order()

    def _migrate_add_pin_order(self) -> None:
        """给**已存在**的数据库补上 ``pin_order`` 列并回填。

        ## 为什么需要迁移

        `CREATE TABLE IF NOT EXISTS` 对**已经建好的**表什么都不做——
        所以老用户的库不会自动多出这一列，随后所有带 `pin_order` 的
        SQL 都会报 `no such column`。

        ## 回填值怎么定

        用户**当前看到的**顶置顺序是 ``ORDER BY id``（旧查询用的）。
        回填时按 ``id DESC`` 依次给 1、2、3……，配合新的
        ``ORDER BY pin_order DESC`` —— **升级后顺序与升级前完全一样**，
        用户不会觉得"顶置列表被重排了"。

        之后再顶置新的，它的 `pin_order` 比谁都大，于是排在最前。

        整个过程放进一个事务：**要么都成，要么都不动**。
        半途失败留着"有列但没回填"的状态，顺序就会乱。
        """
        columns = {
            row[1] for row in self.cursor.execute("PRAGMA table_info(paths)")
        }
        if "pin_order" in columns:
            return
        with self.conn:
            self.cursor.execute(
                "ALTER TABLE paths ADD COLUMN pin_order INTEGER DEFAULT 0")
            pinned = self.cursor.execute(
                "SELECT id FROM paths WHERE is_pinned = 1 ORDER BY id DESC"
            ).fetchall()
            for order, (row_id,) in enumerate(pinned, start=1):
                self.cursor.execute(
                    "UPDATE paths SET pin_order = ? WHERE id = ?",
                    (order, row_id))

    # -- 生命周期 ---------------------------------------------------------

    def close(self) -> None:
        """只关闭连接。

        **这里不再重写整表。** 旧实现在 ``on_close`` 里先 ``DELETE FROM paths``
        再把界面上的行插回去；界面既然是真来源，就没有"写回"的必要，
        而在异常退出时它反而会把没来得及上屏的改动抹掉。
        """
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    # -- 写 ---------------------------------------------------------------

    def record_access(self, path: str, when: str | None = None) -> PathRecord:
        """记一次访问：首次插入计数 1，已存在则计数 +1 并刷新时间。

        一条 SQL 完成 upsert，避免"先查后写"之间的竞态。
        """
        timestamp = when or now_text()
        self.cursor.execute(
            """
            INSERT INTO paths (path, access_count, last_access_time)
            VALUES (?, 1, ?)
            ON CONFLICT(path) DO UPDATE SET
                access_count = access_count + 1,
                last_access_time = excluded.last_access_time
            """,
            (path, timestamp),
        )
        self.conn.commit()
        return self.get(path) or PathRecord(path, 1, timestamp, False)

    def set_pinned(self, path: str, pinned: bool) -> bool:
        """设置/取消顶置。**新顶置的排在最前**（`pin_order` 最大）。

        :return: **是否真的改到了一行**。

        审计查出的缺陷：原来返回 ``None``，于是"改到了 0 行"与"改成功了"
        在调用方看来完全一样。可达路径：这条记录在别处（另一个实例）已被删掉，
        用户点顶置 → 界面显示已顶置 → **重启后没了**，而中间没有任何提示。

        `cursor.rowcount` 是这里唯一的真话来源：``UPDATE`` 没匹配到行时它返回 0。

        ## 顺序怎么维护

        顶置 → ``pin_order = COALESCE(MAX(pin_order), 0) + 1``（比谁都大 ⇒ 最前）。
        取消 → 归 0。

        **取消顶置不重排其他项**：它们的相对顺序不受影响，剩下的那个"最大值"
        仍然有效。所以反复顶置/取消不会让顺序漂移。
        """
        if pinned:
            self.cursor.execute(
                """
                UPDATE paths
                SET is_pinned = 1,
                    pin_order = (SELECT COALESCE(MAX(pin_order), 0) + 1
                                 FROM paths)
                WHERE path = ?
                """,
                (path,),
            )
        else:
            self.cursor.execute(
                "UPDATE paths SET is_pinned = 0, pin_order = 0 WHERE path = ?",
                (path,),
            )
        changed = self.cursor.rowcount
        self.conn.commit()
        return changed > 0

    def remove(self, path: str) -> bool:
        """删除一条记录（路径失效或用户主动删除时调用）。

        :return: **是否真的删掉了一行**（见 :meth:`set_pinned` 的说明）。
        """
        self.cursor.execute("DELETE FROM paths WHERE path = ?", (path,))
        changed = self.cursor.rowcount
        self.conn.commit()
        return changed > 0

    def remove_many(self, paths: list[str]) -> int:
        """**一次事务**删掉多条记录。返回真正删掉的行数。

        ## 为什么不能用 `for path in paths: self.remove(path)`

        审计查出的缺陷（2026-10-17）：多选删除原来是逐条 `remove()` ——
        而 `remove()` 每次自己 `commit()`。于是中途失败（磁盘满 /
        库被别的进程锁住 / 文件只读）就变成：

        * 异常**之前**那几条：已经 DELETE 并提交，**撤不回来了**
        * 界面上它们还在（因为后续重建没跑）
        * 用户以为还在 → 再点「打开」→ `record_access` 又把它们
          **重新 INSERT 回库**（`access_count` 归 1、顶置状态丢失）

        ⇒ 整批放进**一个事务**：要么全成、要么全不成。
        `sqlite3.Connection` 的上下文管理器在异常时自动回滚
        （本项目 `_migrate_add_pin_order` 用的也是这个写法）。

        **注意**：单条 `remove()` 保持原样 —— 它的调用方
        （失效路径删除）本来就只删一条，包事务没有意义。
        """
        if not paths:
            return 0
        with self.conn:
            removed = 0
            for path in paths:
                self.cursor.execute("DELETE FROM paths WHERE path = ?", (path,))
                removed += max(self.cursor.rowcount, 0)
        return removed

    def clear(self) -> None:
        """清空全部记录。"""
        self.cursor.execute("DELETE FROM paths")
        self.conn.commit()

    def replace_all(self, records: list[PathRecord]) -> None:
        """整表替换。**失败时整体回滚，一行都不动。**

        只用于导入/迁移这类**外部数据整体覆盖**的场景，不用于正常退出。

        ## 为什么必须显式回滚

        审计查出的一个**数据丢失**缺陷（`sqlite3` 默认不是自动提交）：

            DELETE FROM paths          ← 旧数据已经进了事务
            INSERT ...                 ← 第 3 条重复 → IntegrityError
            commit()                   ← **没走到**

        中间失败时 DELETE **还挂在那个未提交的事务里**。此后任何一次
        `commit()`（`record_access` / `set_pinned` / `remove` / `clear`，
        以及 `close()` 里的那次）都会把它**变成永久的**——
        于是"导入失败"的后果是**整张表没了**。

        实测过：3 条记录 → `replace_all` 撞 `IntegrityError` → 剩 1 条
        → 一次无关的 `record_access` → **原来那 3 条永久消失**。

        现在用 `with self.conn:` —— `sqlite3.Connection` 的上下文管理器
        **在异常时自动 rollback、正常时自动 commit**，且不会漏掉任何一条
        退出路径。整段替换因此是"要么全成、要么全不动"。
        """
        with self.conn:
            self.cursor.execute("DELETE FROM paths")
            for record in records:
                self.cursor.execute(
                    """
                    INSERT INTO paths (path, access_count, last_access_time, is_pinned)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        record.path,
                        record.access_count,
                        record.last_access_time,
                        1 if record.is_pinned else 0,
                    ),
                )

    # -- 读 ---------------------------------------------------------------

    def get(self, path: str) -> PathRecord | None:
        self.cursor.execute(
            "SELECT path, access_count, last_access_time, is_pinned FROM paths WHERE path = ?",
            (path,),
        )
        row = self.cursor.fetchone()
        return self._row_to_record(row) if row else None

    def load_pinned(self) -> list[PathRecord]:
        """顶置项，**最近顶置的在最前**。

        顺序取自 `pin_order`（不是 `id`）。

        原来用的是 ``ORDER BY id``，那是"首次访问的先后"——与顶置顺序无关。
        后果就是用户报的那条："新条目置顶后会排在所有已置顶条目最后"。
        """
        self.cursor.execute(
            """
            SELECT path, access_count, last_access_time, is_pinned
            FROM paths WHERE is_pinned = 1 ORDER BY pin_order DESC, id DESC
            """
        )
        return [self._row_to_record(row) for row in self.cursor.fetchall()]

    def load_unpinned(self) -> list[PathRecord]:
        """非顶置项，按频次降序（与界面的默认排序一致）。"""
        self.cursor.execute(
            """
            SELECT path, access_count, last_access_time, is_pinned
            FROM paths WHERE is_pinned = 0
            ORDER BY access_count DESC
            """
        )
        return [self._row_to_record(row) for row in self.cursor.fetchall()]

    def count(self) -> int:
        self.cursor.execute("SELECT COUNT(*) FROM paths")
        return int(self.cursor.fetchone()[0])

    @staticmethod
    def _row_to_record(row) -> PathRecord:
        path, access_count, last_access_time, is_pinned = row
        return PathRecord(
            path=path,
            access_count=int(access_count) if access_count is not None else 0,
            last_access_time=last_access_time or "",
            is_pinned=bool(is_pinned),
        )


def default_db_path() -> str:
    """默认数据库位置：``C:\\Users\\<用户>\\file_tracker.db``。

    **注意**：测试与调试会污染真实数据，跑测试前先备份，或用 ``:memory:``。
    """
    import os

    return os.path.join(os.path.expanduser("~"), "file_tracker.db")
