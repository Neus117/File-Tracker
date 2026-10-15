"""数据层与配置层的测试。

用 ``:memory:`` 或临时目录里的数据库，**绝不碰 ``~/file_tracker.db``**——
那是用户的真实数据（项目笔记里明确警告过）。
"""

from __future__ import annotations

import json
import os

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
    store.set_pinned(r"C:\B", True)

    pinned = [r.path for r in store.load_pinned()]
    assert pinned == [r"C:\A", r"C:\B"]          # 按插入顺序
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
