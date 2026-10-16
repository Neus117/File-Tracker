"""数据层与配置层的测试。

用 ``:memory:`` 或临时目录里的数据库，**绝不碰 ``~/file_tracker.db``**——
那是用户的真实数据（项目笔记里明确警告过）。
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from file_tracker.config import DEFAULT_DIRECTORY, Config
from file_tracker.store import PathRecord, PathStore, split_timestamp


@pytest.fixture()
def store():
    instance = PathStore(":memory:")
    yield instance
    instance.close()


# --------------------------------------------------------------------------
# PathStore
# --------------------------------------------------------------------------

def test_record_access_inserts_with_count_one(store):
    record = store.record_access(r"C:\Users")
    assert record.path == r"C:\Users"
    assert record.access_count == 1
    assert record.last_access_time


def test_record_access_increments_on_repeat(store):
    """"频次 +1"必须真的 +1。这是路径栏与双击共用的那条路径。"""
    store.record_access(r"C:\Users")
    store.record_access(r"C:\Users")
    record = store.record_access(r"C:\Users")
    assert record.access_count == 3
    assert store.count() == 1


def test_record_access_refreshes_timestamp(store):
    first = store.record_access(r"C:\Users", when="2026-01-01 00:00:00")
    second = store.record_access(r"C:\Users", when="2026-10-15 12:00:00")
    assert first.access_count == 1
    assert second.last_access_time == "2026-10-15 12:00:00"
    assert store.get(r"C:\Users").last_access_time == "2026-10-15 12:00:00"


def test_pin_and_unpin(store):
    store.record_access(r"C:\A")
    store.record_access(r"C:\B")
    store.set_pinned(r"C:\A", True)

    # **只顶置一条时它当然在最前。** 这一条是用户报的那个缺陷的判据：
    # 先顶置 A，再顶置 B，那么 **B 必须在 A 前面**（最近顶置的在最前）。
    assert [r.path for r in store.load_pinned()] == [r"C:\A"]

    store.set_pinned(r"C:\B", True)
    pinned = [r.path for r in store.load_pinned()]
    assert pinned == [r"C:\B", r"C:\A"], (
        "新顶置的必须排在最前 —— 用户反馈过「新条目置顶后会排在所有"
        f"已置顶条目最后，不符合使用习惯和直觉」，实际得到 {pinned}")
    assert [r.path for r in store.load_unpinned()] == []

    store.set_pinned(r"C:\A", False)
    assert [r.path for r in store.load_pinned()] == [r"C:\B"]
    assert [r.path for r in store.load_unpinned()] == [r"C:\A"]


def test_load_unpinned_orders_by_access_count_desc(store):
    store.record_access(r"C:\rare")
    for _ in range(3):
        store.record_access(r"C:\often")
    store.record_access(r"C:\sometimes")
    store.record_access(r"C:\sometimes")

    assert [r.path for r in store.load_unpinned()] == [
        r"C:\often", r"C:\sometimes", r"C:\rare",
    ]


def test_remove_only_deletes_that_path(store):
    store.record_access(r"C:\A")
    store.record_access(r"C:\B")
    store.remove(r"C:\A")
    assert store.get(r"C:\A") is None
    assert store.get(r"C:\B") is not None


def test_clear_empties_the_table(store):
    store.record_access(r"C:\A")
    store.record_access(r"C:\B")
    store.clear()
    assert store.count() == 0


def test_replace_all_is_a_whole_table_swap(store):
    store.record_access(r"C:\gone")
    store.replace_all([
        PathRecord(r"C:\kept", 5, "2026-10-15 12:00:00", True),
    ])
    assert store.get(r"C:\gone") is None
    assert store.get(r"C:\kept").access_count == 5
    assert [r.path for r in store.load_pinned()] == [r"C:\kept"]


def test_replace_all_rolls_back_on_failure(store):
    """**中途失败时整张表必须原封不动。**

    这是审计查出的一个数据丢失缺陷。`sqlite3` 默认不是自动提交：

        DELETE FROM paths      ← 旧数据进了事务
        INSERT ...             ← 第 3 条重复 → IntegrityError
        commit()               ← 没走到

    中间失败时 DELETE **还挂在那个未提交的事务里**，此后任何一次
    ``commit()``（`record_access` / `set_pinned` / `remove` / `clear`，
    以及 `close()` 里那次）都会把它**变成永久的**——
    于是"导入失败"的后果是**整张表没了**。

    所以这条测试**必须再写一次无关数据**：只断言"失败后还在"是不够的，
    那只证明 DELETE 尚未提交；要证明**回滚过**，得看后续提交会不会
    把那半截事务带出去。

    这就是它当初为什么没被发现——`replace_all` 现在只有测试在调，
    而原来的测试只验了成功路径。
    """
    for name in (r"C:\A", r"C:\B", r"C:\C"):
        store.record_access(name)
    assert store.count() == 3

    duplicated = [
        PathRecord(r"C:\X", 1, "2026-01-01 00:00:00", False),
        PathRecord(r"C:\Y", 1, "2026-01-01 00:00:00", False),
        PathRecord(r"C:\X", 1, "2026-01-01 00:00:00", False),   # 重复 → 触发错误
    ]
    with pytest.raises(sqlite3.IntegrityError):
        store.replace_all(duplicated)

    # ① 失败瞬间：旧数据应当还在
    assert store.count() == 3, "失败的 replace_all 把表删掉了一部分"

    # ② **关键**：一次无关的写入（会 commit）。若没回滚，
    #    那个待提交的 DELETE 会在此刻永久生效。
    store.record_access(r"C:\ZZZ")
    assert store.count() == 4, (
        "一次无关的 commit 把失败的 replace_all 带出去了——"
        "原来的 3 条被永久删除")
    remaining = sorted(record.path for record in store.load_unpinned())
    assert remaining == [r"C:\A", r"C:\B", r"C:\C", r"C:\ZZZ"], remaining


def test_replace_all_rolls_back_even_if_close_follows(tmp_path):
    """`close()` 里那次 `commit()` 同样不能把半截事务带出去。

    这是同一个缺陷的另一条出口：导入失败之后用户直接关程序，
    而 `close()` 会 commit —— 原来的实现在这里也会丢数据。

    **用真实文件**而不是 `:memory:`：要验的是"关掉再打开之后数据还在"，
    内存库关掉就没了。
    """
    path = str(tmp_path / "store.db")
    store = PathStore(path)
    for name in (r"C:\A", r"C:\B"):
        store.record_access(name)

    duplicated = [
        PathRecord(r"C:\X", 1, "2026-01-01 00:00:00", False),
        PathRecord(r"C:\X", 1, "2026-01-01 00:00:00", False),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        store.replace_all(duplicated)

    store.close()          # ← 原来这里会把 DELETE 提交掉

    reopened = PathStore(path)
    try:
        assert sorted(record.path for record in reopened.load_unpinned()) == \
            [r"C:\A", r"C:\B"], "关程序时把失败的替换提交了，数据丢了"
    finally:
        reopened.close()


def test_get_missing_path_returns_none(store):
    assert store.get(r"C:\never-seen") is None


def test_store_persists_across_reopen(tmp_path):
    """真实文件上的往返—— ``:memory:`` 测不出"退出时到底写没写进去"。"""
    db_file = str(tmp_path / "test.db")

    first = PathStore(db_file)
    first.record_access(r"C:\Persisted")
    first.record_access(r"C:\Persisted")
    first.set_pinned(r"C:\Persisted", True)
    first.close()

    second = PathStore(db_file)
    record = second.get(r"C:\Persisted")
    assert record.access_count == 2
    assert record.is_pinned is True
    assert [r.path for r in second.load_pinned()] == [r"C:\Persisted"]
    second.close()


def test_close_does_not_wipe_the_table(tmp_path):
    """回归测试：旧实现在退出时 ``DELETE`` 全表再从界面插回。

    那条路径一旦界面与数据库不同步，就会把数据抹掉。现在 ``close()``
    只提交、不重写——这条测试守住这个行为。
    """
    db_file = str(tmp_path / "test.db")
    store = PathStore(db_file)
    store.record_access(r"C:\Keep")
    store.close()

    reopened = PathStore(db_file)
    assert reopened.count() == 1
    reopened.close()


# --------------------------------------------------------------------------
# split_timestamp —— "访问日期"与"访问时间"分两列显示
# --------------------------------------------------------------------------

def test_split_timestamp_halves():
    """用户要求日期与时间容易区分，所以显示时拆成两列。

    数据库里仍存整串（`store.TIME_FORMAT`），只在渲染时拆开。
    """
    assert split_timestamp("2026-10-15 13:01:17") == ("2026-10-15", "13:01:17")


def test_split_timestamp_keeps_unknown_formats_readable():
    """格式不对时整串放在日期列、时间列留空。

    **不能抛异常，也不能丢掉整行**——时间戳来自旧版本数据库
    （v1.0.3 用的是 REAL 时间戳），格式未必统一。用户宁可看到一串
    看不懂的字符，也不愿看到那一行凭空消失。
    """
    assert split_timestamp("1750000000.0") == ("1750000000.0", "")
    assert split_timestamp("2026-10-15") == ("2026-10-15", "")
    assert split_timestamp("") == ("", "")
    assert split_timestamp(None) == ("", "")


def test_split_timestamp_only_splits_on_the_first_space():
    """多余的空格不能被丢掉后半个字段。"""
    assert split_timestamp("2026-10-15 13:01:17 extra") == (
        "2026-10-15", "13:01:17 extra",
    )


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def test_config_defaults_when_file_missing(tmp_path):
    config = Config(str(tmp_path / "config.json"))
    assert config.get_last_directory() == DEFAULT_DIRECTORY
    assert config.get_scroll_position() == 0.0


def test_config_recovers_from_corrupt_json(tmp_path):
    """损坏的配置文件不能让程序起不来。"""
    path = tmp_path / "config.json"
    path.write_text("{ this is not json", encoding="utf-8")
    config = Config(str(path))
    assert config.get_last_directory() == DEFAULT_DIRECTORY


# --------------------------------------------------------------------------
# 配置的**耐久性** —— 两个真实的数据丢失缺陷
# --------------------------------------------------------------------------

def test_corrupt_config_is_backed_up_not_silently_dropped(tmp_path):
    """损坏的配置要**留一份**，不能静默变成空。

    原来的行为是 ``except: self._data = {}``，然后下一次 `save()` 把 ``{}``
    写回去 —— **原设置永久丢失，而且没有任何提示**。配置文件是明确预期
    会被手改的（`get_sort_column` 的注释就写着），所以"内容不合法"是
    正常输入，不是异常情况。

    判据：损坏之后要出现 ``config.json.corrupt``，且**内容与原来一致**。
    """
    path = tmp_path / "config.json"
    broken = '{"last_directory": "D:\\\\Work", "language": "zh",,}'
    path.write_text(broken, encoding="utf-8")

    config = Config(str(path))
    assert config.get_last_directory() == DEFAULT_DIRECTORY   # 回退了

    backup = tmp_path / "config.json.corrupt"
    assert backup.exists(), "损坏的配置没有被备份下来——用户的设置就永久没了"
    assert backup.read_text(encoding="utf-8") == broken, (
        "备份的内容与损坏前的文件不一致，那备份就没意义了")


def test_missing_config_is_not_treated_as_corrupt(tmp_path):
    """**第一次运行**不是损坏，不该产生 .corrupt 文件。"""
    Config(str(tmp_path / "config.json"))
    assert not (tmp_path / "config.json.corrupt").exists()


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    """保存必须走"临时文件 + 原子改名"，且**结束后不留临时文件**。

    原地 ``open(path, "w")`` 一执行旧内容就没了；写到一半失败
    （断电、被杀、磁盘满）就留下半截文件 → 下次读到 ``JSONDecodeError``
    → 所有偏好丢失。而写入**非常频繁**（每点一次表头就存一次），
    所以这个组合撞上损坏只是时间问题。
    """
    path = tmp_path / "config.json"
    config = Config(str(path))
    config.set_last_directory(str(tmp_path))
    config.save()

    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "config.json"]
    assert not leftovers, f"保存后留下了临时文件：{leftovers}"
    # 存出来的必须是**完整可解析**的 JSON
    assert json.loads(path.read_text(encoding="utf-8"))["last_directory"] == \
        str(tmp_path)


def test_save_failure_does_not_destroy_the_old_config(tmp_path, monkeypatch):
    """**写失败时旧配置必须完好。**

    这是原子写真正的价值：非原子版本一旦开始写就已经把旧内容截断了，
    所以"写失败"等于"配置没了"。
    """
    path = tmp_path / "config.json"
    config = Config(str(path))
    config.set_last_directory("D:\\Keep me")
    config.save()
    good = path.read_text(encoding="utf-8")

    # 让 json.dump 在写的过程中炸掉，模拟"写到一半失败"
    def boom(*_args, **_kwargs):
        raise OSError("模拟磁盘满 / 中断")

    monkeypatch.setattr(json, "dump", boom)
    config.set_last_directory("D:\\Should not survive")
    with pytest.raises(OSError):
        config.save()

    assert path.read_text(encoding="utf-8") == good, (
        "写失败后旧配置被破坏了——那正是非原子写的问题")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "config.json"]
    assert not leftovers, f"写失败后留下了临时文件：{leftovers}"


def test_config_falls_back_when_last_directory_disappeared(tmp_path):
    """配置里存着一个已经拔掉的移动盘符时，必须回退而不是把空树交给界面。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"last_directory": r"Z:\definitely-gone"}),
                    encoding="utf-8")
    assert Config(str(path)).get_last_directory() == DEFAULT_DIRECTORY


def test_config_round_trips_last_directory(tmp_path):
    path = str(tmp_path / "config.json")
    config = Config(path)
    config.set_last_directory(str(tmp_path))
    config.save()

    assert Config(path).get_last_directory() == str(tmp_path)


def test_scroll_position_is_clamped_to_unit_range(tmp_path):
    config = Config(str(tmp_path / "config.json"))
    config.set_scroll_position(1.7)
    assert config.get_scroll_position() == 1.0
    config.set_scroll_position(-3)
    assert config.get_scroll_position() == 0.0


def test_saving_scroll_position_does_not_lose_last_directory(tmp_path):
    """回归测试：旧实现里两次独立的 ``open(..., 'w')`` 会互相抹掉对方。

    ``save_last_directory`` 写 ``{'last_directory': ...}``，
    ``save_scroll_position`` 先读再改再写——只有后者读。
    所以"先存滚动位置、再存目录"是安全的，反过来会把目录整个丢掉。
    现在两个字段共用一份内存数据、一次写回。
    """
    path = str(tmp_path / "config.json")

    config = Config(path)
    config.set_last_directory(str(tmp_path))
    config.set_scroll_position(0.42)
    config.save()

    reloaded = Config(path)
    assert reloaded.get_last_directory() == str(tmp_path)
    assert reloaded.get_scroll_position() == 0.42


def test_save_creates_missing_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "config.json"
    config = Config(str(nested))
    config.set_scroll_position(0.5)
    config.save()
    assert os.path.exists(nested)


# --------------------------------------------------------------------------
# 零行写入不能当成成功（审计 M4）
# --------------------------------------------------------------------------

def test_set_pinned_reports_whether_a_row_changed(store):
    """`set_pinned` 必须告诉调用方**有没有真的改到一行**。

    原来返回 `None`，于是"改到 0 行"与"改成功"在调用方看来一样。
    可达路径：这条记录在别处（另一个实例）已被删掉，
    用户点顶置 → 界面显示已顶置 → **重启后没了**，中间没有任何提示。
    """
    store.record_access(r"C:\Exists")
    assert store.set_pinned(r"C:\Exists", True) is True

    # 库里没有这一条 —— 必须如实回报 False，而不是默默"成功"
    assert store.set_pinned(r"C:\Never-recorded", True) is False


def test_remove_reports_whether_a_row_was_deleted(store):
    """`remove` 同理：删到 0 行时调用方不该说"已删除"。

    用户报过这个现象：导航窗格停在一个失效路径上（比如拔掉的 U 盘），
    那个路径**从来就不是一条记录**；点删除后程序说"已从记录中删除"，
    而实际什么都没删。
    """
    store.record_access(r"C:\Real")
    assert store.remove(r"C:\Real") is True
    assert store.remove(r"C:\Real") is False        # 第二次已经没有可删的了
    assert store.remove(r"C:\Never-recorded") is False


def test_pin_order_is_the_same_in_memory_and_in_the_store(tmp_path):
    """顶置顺序**跨重启保持一致**，而且**新顶置的在最前**。

    ## 这个功能我改错过两次，两次的原因一样

    **第一次**：`on_pin` 用 ``insert(0, ...)``（新的排最前），
    而启动时读的是 ``ORDER BY id``（**首次访问**的顺序）。
    两者不一致 ⇒ 用户刚顶置的那条会在重启后跳到别的位置。

    **第二次（我的错）**：为了"不需要迁移"，我把 `on_pin` 改成 ``append``，
    让内存与 ``ORDER BY id`` 一致——**重启漂移治好了，却弄坏了看得见的行为**。
    用户反馈：

    > 新条目置顶后会排在所有已置顶条目最后，这不符合使用习惯和直觉。

    **根子是一直没有"顶置顺序"这个东西**，只有 `id`（首次访问的先后）。
    拿它当顶置顺序，就只能在"新顶置排哪"和"重启后不变"里二选一。

    现在 `pin_order` 把顺序真的存下来了，两个要求可以同时满足。

    **必须用真实文件**：`store` fixture 是 ``:memory:``，一关就没了，
    验不了"重启后顺序不变"。
    """
    path = str(tmp_path / "pins.db")
    store = PathStore(path)
    try:
        for name in (r"C:\First", r"C:\Second", r"C:\Third"):
            store.record_access(name)
        for name in (r"C:\First", r"C:\Second", r"C:\Third"):
            assert store.set_pinned(name, True) is True

        # **最近顶置的在最前** —— 与"首次访问顺序"刚好相反
        assert [r.path for r in store.load_pinned()] == [
            r"C:\Third", r"C:\Second", r"C:\First"]
    finally:
        store.close()

    # 重新打开（模拟重启）之后顺序不变 —— 这才是第一版真正的缺陷所在
    reopened = PathStore(path)
    try:
        assert [r.path for r in reopened.load_pinned()] == [
            r"C:\Third", r"C:\Second", r"C:\First"]

        # 重启之后再顶置一条，它仍然排最前（而不是跑到最后）
        reopened.record_access(r"C:\Fourth")
        assert reopened.set_pinned(r"C:\Fourth", True) is True
        assert [r.path for r in reopened.load_pinned()] == [
            r"C:\Fourth", r"C:\Third", r"C:\Second", r"C:\First"]
    finally:
        reopened.close()


def test_pin_order_migration_preserves_what_the_user_sees(tmp_path):
    """升级到 `pin_order` 时**不能把用户现有的顶置列表重排**。

    老库没有 `pin_order` 列，而 ``CREATE TABLE IF NOT EXISTS`` 对已存在的表
    什么都不做——所以必须显式迁移，否则所有带 `pin_order` 的 SQL 都会报
    ``no such column``，**用户一升级程序就起不来**。

    回填的关键：**按用户升级前看到的顺序**（旧的 ``ORDER BY id``）
    依次给 1、2、3……，配合新的 ``ORDER BY pin_order DESC``，
    升级前后看到的顺序完全一样。

    这里手工造一个**旧 schema** 的库，而不是用当前代码建——
    用当前代码建的库已经有那一列了，测不出迁移。
    """
    db = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE paths (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                access_count INTEGER DEFAULT 1,
                last_access_time TEXT,
                is_pinned INTEGER DEFAULT 0
            )
            """
        )
        rows = [("p1", 1), ("u1", 0), ("p2", 1), ("u2", 0), ("p3", 1)]
        for index, (name, pinned) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO paths (id, path, access_count,"
                " last_access_time, is_pinned) VALUES (?, ?, 1, ?, ?)",
                (index, name, "2026-01-01 00:00:00", pinned),
            )
        conn.commit()
        # 旧查询给出的顺序 == 用户升级前看到的顺序
        before = [r[0] for r in conn.execute(
            "SELECT path FROM paths WHERE is_pinned = 1 ORDER BY id")]
    finally:
        conn.close()

    assert before == ["p1", "p2", "p3"]

    store = PathStore(db)
    try:
        # 迁移之后顺序**必须一模一样**
        assert [r.path for r in store.load_pinned()] == before, (
            "迁移不得重排用户已有的顶置列表")

        # 而新顶置的仍然排最前
        assert store.set_pinned("u1", True) is True
        assert [r.path for r in store.load_pinned()] == [
            "u1", "p1", "p2", "p3"]
    finally:
        store.close()

    # 迁移只跑一次：再开一遍不应改变任何东西
    again = PathStore(db)
    try:
        assert [r.path for r in again.load_pinned()] == [
            "u1", "p1", "p2", "p3"]
    finally:
        again.close()
