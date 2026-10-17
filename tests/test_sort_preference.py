"""排序偏好的测试：默认值、按列记住方向、以及非法输入的处理。

用户要求："可以选择下次启动时的排序方式。目前是每次启动默认频次排序，
太死板，我希望用户能根据自己的习惯调节。"

这里测的是**机制**：默认是什么、存了什么就读回什么、
认不出的值会不会把程序带坏。
"""

from __future__ import annotations

import pytest

from file_tracker import config as config_module
from file_tracker import core


# --------------------------------------------------------------------------
# 可排序列的定义
# --------------------------------------------------------------------------

def test_default_is_still_count_descending():
    """**默认必须是"频次、降序"** —— 那是 1.1 以来的行为。

    老用户升级之后第一眼看到的东西不该变。这一条要是被改动，
    用户会以为自己的记录丢了（顺序全变了）。
    """
    spec = core.find_sort_spec(None)
    assert spec.key == core.DEFAULT_SORT_KEY == "count"
    assert spec.default_reverse is True


def test_every_spec_has_a_natural_default_direction():
    """每一列的默认方向都要符合"第一眼想看到什么"。

    路径用升序（A→Z），其余用降序（最多/最近在前）。
    只用一个全局方向的话，点"路径"会得到 Z→A——不是用户要的。
    """
    by_key = {spec.key: spec for spec in core.SORT_SPECS}
    assert by_key["path"].default_reverse is False
    assert by_key["count"].default_reverse is True
    # 日期与时间已合并成一个 `time`（用户 2026-10-17）——"最近访问的在前"
    assert by_key["time"].default_reverse is True


def test_unknown_key_falls_back_instead_of_raising():
    """配置文件是可以手改的，写错一个字符串不该让程序起不来。"""
    # 注意 `"time"` 不在这个列表里 —— 它是**合法键**（两列合并后新增的）
    for bogus in ("", "bogus", "COUNT", None, "0", "date "):
        assert core.find_sort_spec(bogus).key == core.DEFAULT_SORT_KEY


def test_legacy_sort_keys_map_to_time():
    """旧配置里的 `"date"` / `"clock"` 要映射到 `"time"`。

    两列时代用户可能选过"按访问日期"或"按访问时间"排序。升级后这两个键
    不存在了 —— **当成未知键丢回默认**会让"我一直按时间排"的人
    莫名其妙变成按频次排。所以映射，而不是回退。
    """
    assert core.find_sort_spec("date").key == "time"
    assert core.find_sort_spec("clock").key == "time"
    assert core.LEGACY_SORT_KEYS == {"date": "time", "clock": "time"}


def test_sort_keys_are_stable_identifiers():
    """标识是**字符串**而不是列号：列号会因为中间插一列而错位，
    而且写进配置以后没法读。"""
    assert core.sort_keys() == ("path", "count", "time")
    for key in core.sort_keys():
        assert isinstance(key, str) and key


def test_column_order_matches_sort_spec_order():
    """`app` 里"列号 → 排序列"那张表必须与 `SORT_SPECS` **同序同长**。

    这是表头点击的核心不变量：点第 N 列就要按第 N 个 spec 排。
    两张表一旦错位，用户点"频次"会按"日期"排——而且不会有任何报错。

    **写成测试而不是模块级 `assert`**：`python -O` 会去掉 assert，
    这个不变量就静默消失了。
    """
    from file_tracker import app as app_module

    assert app_module._COLUMN_SORT_KEYS == tuple(
        spec.key for spec in core.SORT_SPECS)
    assert len(app_module._COLUMN_SORT_KEYS) == len(app_module.COLUMNS)


def test_column_labels_align_with_sort_specs():
    """列标题的顺序也要与 `SORT_SPECS` 对齐。

    否则设置里选"访问日期"，标题显示的却是别的东西。
    """
    from file_tracker import app as app_module
    from file_tracker import lang

    saved = lang._chinese
    try:
        lang.apply(lang.PREFERENCE_CHINESE)
        labels = app_module.column_labels()
        for label, spec in zip(labels, core.SORT_SPECS):
            assert label == spec.chinese, f"{label!r} != {spec.chinese!r}"
    finally:
        lang._chinese = saved


def test_column_key_round_trip():
    """列号 ↔ 排序列标识必须能来回换，且认不出的输入有回退。"""
    from file_tracker import app as app_module

    for column, key in enumerate(app_module._COLUMN_SORT_KEYS):
        assert app_module._sort_key_of(column) == key
        assert app_module._column_of(key) == column
    # 越界与未知都回退到默认，而不是抛异常
    assert app_module._sort_key_of(99) == core.DEFAULT_SORT_KEY
    assert app_module._sort_key_of(-1) == core.DEFAULT_SORT_KEY
    assert app_module._column_of("bogus") == app_module._COLUMN_SORT_KEYS.index(
        core.DEFAULT_SORT_KEY)


def test_labels_switch_language():
    """显示名跟随语言——设置界面里的按钮文字就是它。"""
    from file_tracker import lang

    saved = lang._chinese
    try:
        lang.apply(lang.PREFERENCE_CHINESE)
        assert core.find_sort_spec("count").label() == "频次"
        lang.apply(lang.PREFERENCE_ENGLISH)
        assert core.find_sort_spec("count").label() == "Count"
    finally:
        lang._chinese = saved


# --------------------------------------------------------------------------
# 配置持久化
# --------------------------------------------------------------------------

def test_sort_column_defaults_to_none(tmp_path):
    """没设过就是 ``None``（由调用方回退到默认），不是 "count"。

    这样"用户从没表达过偏好"和"用户明确选了频次"是两件可区分的事。
    """
    cfg = config_module.Config(str(tmp_path / "c.json"))
    assert cfg.get_sort_column() is None


def test_sort_column_round_trips(tmp_path):
    path = str(tmp_path / "c.json")
    cfg = config_module.Config(path)
    cfg.set_sort_column("path")
    cfg.save()
    assert config_module.Config(path).get_sort_column() == "path"


def test_sort_column_rejects_unknown(tmp_path):
    cfg = config_module.Config(str(tmp_path / "c.json"))
    cfg.set_sort_column("bogus")
    assert cfg.get_sort_column() is None


def test_sort_direction_is_per_column(tmp_path):
    """**方向按列存。**

    只存一个全局方向的话，用户在"频次"上按了一次升序，
    再切到"路径"就会得到 Z→A——那不是他要的第一眼结果。
    """
    cfg = config_module.Config(str(tmp_path / "c.json"))
    cfg.set_sort_direction("count", False)
    cfg.set_sort_direction("path", True)

    assert cfg.get_sort_direction("count") is False
    assert cfg.get_sort_direction("path") is True
    # 没设过的列返回 None（表示"用该列的默认"），而不是被别的列带跑
    assert cfg.get_sort_direction("time") is None


def test_sort_direction_round_trips(tmp_path):
    path = str(tmp_path / "c.json")
    cfg = config_module.Config(path)
    cfg.set_sort_direction("time", False)
    cfg.save()
    assert config_module.Config(path).get_sort_direction("time") is False


def test_sort_direction_rejects_unknown_column(tmp_path):
    cfg = config_module.Config(str(tmp_path / "c.json"))
    cfg.set_sort_direction("bogus", True)
    assert cfg._data.get("sort_directions") in (None, {})


def test_sort_direction_rejects_non_bool_in_file(tmp_path):
    """手改配置把方向写成字符串 → 当成"没设过"，而不是原样返回。

    原样返回的话 `if direction is None` 判不出来，后面会拿一个字符串
    去当 `reverse=` 用——排序方向随机。
    """
    path = tmp_path / "c.json"
    path.write_text('{"sort_directions": {"count": "yes"}}', encoding="utf-8")
    assert config_module.Config(str(path)).get_sort_direction("count") is None


def test_sort_direction_survives_a_broken_section(tmp_path):
    """`sort_directions` 整段被写坏（不是 dict）时不能崩。"""
    path = tmp_path / "c.json"
    path.write_text('{"sort_directions": 42}', encoding="utf-8")
    cfg = config_module.Config(str(path))
    assert cfg.get_sort_direction("count") is None
    # 还能正常写回去
    cfg.set_sort_direction("count", False)
    assert cfg.get_sort_direction("count") is False


def test_setting_sort_does_not_drop_other_keys(tmp_path):
    """存排序不能把语言或目录抹掉——`config.py` 里记过这个缺陷。"""
    path = str(tmp_path / "c.json")
    cfg = config_module.Config(path)
    cfg.set_language("en")
    cfg.set_last_directory("D:\\Work")
    cfg.set_sort_column("time")
    cfg.set_sort_direction("time", False)
    cfg.save()

    reloaded = config_module.Config(path)
    assert reloaded.get_language() == "en"
    assert reloaded._data["last_directory"] == "D:\\Work"
    assert reloaded.get_sort_column() == "time"
    assert reloaded.get_sort_direction("time") is False


def test_sort_direction_update_does_not_mutate_shared_dict(tmp_path):
    """`set_sort_direction` 要**整块换掉**那个 dict，不要原地改。

    原地改的话，`_data` 里那个 dict 若是从别处引用来的，
    改它等于偷偷改了别人的状态——本项目已经因为这类共享可变状态
    修过好几次（配置互相覆盖就是其中之一）。
    """
    cfg = config_module.Config(str(tmp_path / "c.json"))
    cfg.set_sort_direction("count", True)
    snapshot = cfg._data["sort_directions"]
    cfg.set_sort_direction("path", False)
    # 原来那一份不能被改动
    assert snapshot == {"count": True}
    assert cfg._data["sort_directions"] == {"count": True, "path": False}
