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
    is_pinned INTEGER DEFAULT 0
)
"""

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


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

    def set_pinned(self, path: str, pinned: bool) -> None:
        """设置/取消顶置。``pinned_paths`` 的顺序由调用方维护（``id`` 序）。"""
        self.cursor.execute(
            "UPDATE paths SET is_pinned = ? WHERE path = ?",
            (1 if pinned else 0, path),
        )
        self.conn.commit()

    def remove(self, path: str) -> None:
        """删除一条记录（路径失效或用户主动删除时调用）。"""
        self.cursor.execute("DELETE FROM paths WHERE path = ?", (path,))
        self.conn.commit()

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
        """顶置项，按插入顺序（用户顶置的先后）。"""
        self.cursor.execute(
            """
            SELECT path, access_count, last_access_time, is_pinned
            FROM paths WHERE is_pinned = 1 ORDER BY id
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
