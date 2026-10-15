"""国际化（中英双语）与语言偏好的测试。

照搬 Roboc `src/Roboc.Core/Model/Lang.cs` 的做法：**文案写成
``L("中文", "English")``，两半都在调用点**，不用资源文件。
资源文件的失败方式是"键漏了就给用户看键名"，而两个参数在语法上
不允许只写一个。

这里测的是**机制**，不是具体某句翻译：
系统检测的回落、偏好的优先级、以及"配置里存了非法值不能崩"。
"""

from __future__ import annotations

import io
import os

import pytest

from file_tracker import config as config_module
from file_tracker import lang


@pytest.fixture(autouse=True)
def _restore_language():
    """每个用例跑完都把语言恢复成"未定"，**别把状态漏给下一个用例**。

    `lang` 是模块级单例，一个用例 `apply("en")` 之后不还原，
    后面所有用例都会在英文环境下跑——那种失败极难定位。
    """
    original = lang._chinese
    yield
    lang._chinese = original


# --------------------------------------------------------------------------
# 检测与覆盖
# --------------------------------------------------------------------------

def test_apply_english_overrides_system_detection():
    """存了 ``en`` 就是英文，**不会被系统语言切回去**。

    这是"中文系统上特意选了英文"那个场景。设置是每用户的、
    检测是每机器的，所以保存的值优先。
    """
    lang.apply(lang.PREFERENCE_ENGLISH)
    assert lang.is_chinese() is False
    assert lang.pick("中文", "English") == "English"


def test_apply_chinese_overrides_system_detection():
    lang.apply(lang.PREFERENCE_CHINESE)
    assert lang.is_chinese() is True
    assert lang.pick("中文", "English") == "中文"


def test_apply_none_falls_back_to_system_detection():
    """``None`` 表示"配置里没存过" → 问系统。

    判据是"返回了一个 bool"，而不是具体值——本机是中文系统，
    但在英文机器上跑 CI 时不该失败。
    """
    detected = lang.apply(None)
    assert isinstance(detected, bool)
    assert lang.is_chinese() is detected


def test_unknown_preference_falls_back_to_system():
    """认不出的偏好当成"没存过"，而不是保持上一次的状态。

    配置文件是可以手改的；写错一个字符串不该让界面卡在某种语言上。
    """
    lang.apply(lang.PREFERENCE_ENGLISH)
    assert lang.is_chinese() is False
    detected = lang.apply("klingon")
    assert isinstance(detected, bool)


def test_preference_round_trips():
    assert lang.preference(True) == lang.PREFERENCE_CHINESE
    assert lang.preference(False) == lang.PREFERENCE_ENGLISH


def test_display_names_cover_every_choice():
    """**每一种选项都要有显示名**，否则设置界面会 ``KeyError``。

    界面从 `CHOICES` 遍历、用 `DISPLAY_NAMES[value]` 取名，
    所以这两者一旦不一致就会在打开设置时崩——加一种语言时最容易漏。
    """
    for value in lang.CHOICES:
        assert value in lang.DISPLAY_NAMES
        assert lang.DISPLAY_NAMES[value], f"{value} 的显示名不能为空"


def test_language_names_are_not_translated():
    """语言名**用自己的语言写**："English" 在中文界面里也得是 "English"。

    一个只看得懂英文的人在中文界面里找英文选项，翻成"英文"他就找不到了。
    """
    assert lang.DISPLAY_NAMES[lang.PREFERENCE_ENGLISH] == "English"
    assert lang.DISPLAY_NAMES[lang.PREFERENCE_CHINESE] == "中文"


# --------------------------------------------------------------------------
# 系统检测
# --------------------------------------------------------------------------

def test_detect_uses_low_byte_of_lang_id():
    """只看 LANGID 的**低字节**：一条判断覆盖简体/繁体/香港/新加坡。

    它们只有高字节不同（0x0804 / 0x0404 / 0x0C04 / 0x1004），
    低字节都是 0x04。
    """
    for lang_id in (0x0804, 0x0404, 0x0C04, 0x1004):
        assert (lang_id & 0xFF) == lang.LANGUAGE_CHINESE


def test_english_lang_id_is_not_chinese():
    for lang_id in (0x0409, 0x0809, 0x0C09):     # en-US / en-GB / en-AU
        assert (lang_id & 0xFF) != lang.LANGUAGE_CHINESE


@pytest.mark.parametrize("value,expected", [
    ("zh_CN.UTF-8", True),
    ("zh-TW", True),
    ("chinese", True),
    ("en_US.UTF-8", False),
    ("C", False),
    ("", False),
])
def test_environment_fallback(value, expected, monkeypatch):
    """``GetUserDefaultUILanguage`` 不可用时的兜底（非 Windows / 测试）。"""
    for name in ("LANG", "LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", value)
    assert lang._detect_from_environment() is expected


# --------------------------------------------------------------------------
# 配置持久化
# --------------------------------------------------------------------------

def test_config_language_defaults_to_none(tmp_path):
    """**没设过就是 ``None``，不是 ``"en"``。**

    两者是两件事：``None`` = 问系统，``"en"`` = 用户明确选了英文。
    把默认写成 "en" 会让中文系统上的用户第一次启动就看到英文。
    """
    cfg = config_module.Config(str(tmp_path / "c.json"))
    assert cfg.get_language() is None


def test_config_language_round_trips(tmp_path):
    path = str(tmp_path / "c.json")
    cfg = config_module.Config(path)
    cfg.set_language(lang.PREFERENCE_ENGLISH)
    cfg.save()
    assert config_module.Config(path).get_language() == "en"


def test_config_rejects_unknown_language(tmp_path):
    cfg = config_module.Config(str(tmp_path / "c.json"))
    cfg.set_language("klingon")
    assert cfg.get_language() is None


def test_config_ignores_bogus_language_in_file(tmp_path):
    """手改配置写了个非法值 → 当成"没存过"，而不是原样返回。

    原样返回的话，`apply()` 会走到 `else` 分支问系统——结果一样，
    但 `get_language()` 的调用方（设置界面）会把非法值当成当前选项，
    界面上就没有任何一项是选中的。
    """
    path = tmp_path / "c.json"
    path.write_text('{"language": "klingon"}', encoding="utf-8")
    assert config_module.Config(str(path)).get_language() is None


def test_config_languages_match_lang_module():
    """`config` 与 `lang` 的取值必须同源，不能各抄一份字面量。

    两份实现迟早不一致——本项目已经因为"同一个东西写了两遍"修过好几次
    （`set_icon`、`load_last_directory`、分隔线几何）。
    """
    assert tuple(config_module.LANGUAGES) == tuple(lang.CHOICES)


def test_saving_language_does_not_drop_other_keys(tmp_path):
    """存语言**不能**把别的配置项抹掉。

    这正是 `config.py` 模块文档里记的那个缺陷："先保存目录、再保存滚动位置"
    会把 `last_directory` 整个抹掉。所以这里用同一个 Config 实例连着写两项。
    """
    path = str(tmp_path / "c.json")
    cfg = config_module.Config(path)
    cfg.set_last_directory("D:\\Work")
    cfg.set_language(lang.PREFERENCE_ENGLISH)
    cfg.save()

    reloaded = config_module.Config(path)
    assert reloaded.get_language() == "en"
    assert reloaded._data["last_directory"] == "D:\\Work"


# --------------------------------------------------------------------------
# 设置图标（用户要求直接拿 Roboc 的那一份）
# --------------------------------------------------------------------------

def test_settings_icon_asset_exists_and_is_a_png():
    """设置按钮的图标必须在，且**确实是一个 PNG**。

    `_build_icon_button` 在图片缺失时会**退化成文字按钮**——
    功能还在，但用户看到的就是"设置按钮没有图标"。
    所以这条测的是"资源在位"，而不是"加载失败不崩"。

    **这里不用 `wx.Image` 解码。** pytest 套件刻意不依赖 GUI
    （CI 上没有桌面会话），一碰 wx 就可能要 `wx.App`。
    所以只核文件头与尺寸字段——真正的"能不能画出来"
    由 `tools/verify_gui.py` 在真实桌面会话里断言。
    """
    from file_tracker.core import resource_path

    path = resource_path(os.path.join("images", "settings.png"))
    assert os.path.exists(path), f"settings.png 不存在：{path}"

    with open(path, "rb") as handle:
        head = handle.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", "不是 PNG（文件头不对）"
    # IHDR 紧跟在 8 字节签名 + 4 字节长度 + 4 字节类型之后
    width = int.from_bytes(head[16:20], "big")
    height = int.from_bytes(head[20:24], "big")
    assert width > 0 and height > 0, f"PNG 尺寸非法：{width}x{height}"


def test_settings_icon_comes_from_roboc_original():
    """这一份是从 Roboc 的 ``settings.ico`` 转出来的。

    用户明确要求："图标直接复制
    ``D:\\Coding\\MyGitHub\\Roboc\\assets\\icons\\settings.ico`` 拿过来用。"
    所以仓库里同时留着那个 ico，便于以后重新导出（比如要换尺寸）。
    """
    from file_tracker.core import resource_path

    ico = resource_path(os.path.join("images", "settings.ico"))
    assert os.path.exists(ico), "settings.ico 不在了——它是 png 的源"
    with open(ico, "rb") as handle:
        head = handle.read(4)
    # ICO 文件头：保留位 0x0000 + 类型 0x0001
    assert head[:2] == b"\x00\x00" and head[2:4] == b"\x01\x00", \
        "settings.ico 不是有效的 ICO"


# --------------------------------------------------------------------------
# 文案不能"在 import 时被冻结" —— 一个真实缺陷
# --------------------------------------------------------------------------

def test_path_bar_hint_is_a_property_not_a_frozen_class_attribute():
    """`PathBar.HINT` 必须是 **property**，不能是类属性。

    ## 这条测试防的是什么

    原来是 ``HINT = L("输入或粘贴路径", "Type or paste a path")``。
    **类属性在 import 时求值一次**，而那时语言还没定下来
    （`lang.apply` 在 `FileTracker.__init__` 里、建界面之前才调）。

    后果（审计实测）：中文系统上 import widgets → `HINT` 冻结成中文
    → 用户选了英文 → **每次启动看到的都还是中文提示**，
    只有去设置里重选一次语言才会被 `retranslate` 改过来。
    英文系统上选中文，镜像同样成立。

    ## 为什么静态查而不是跑起来查

    `PathBar` 要建 `wx` 面板，而这一组测试是**不碰 GUI** 的
    （CI 上没有桌面会话）。要守住的不变量"是不是 property"
    在 AST 上就能确定地判出来，比建窗口更可靠，也不依赖环境。
    """
    import ast

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "file_tracker", "widgets.py")
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    path_bar = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "PathBar":
            path_bar = node
            break
    assert path_bar is not None, "找不到 PathBar 类"

    property_names = {
        item.name for item in path_bar.body
        if isinstance(item, ast.FunctionDef)
        and any(isinstance(deco, ast.Name) and deco.id == "property"
                for deco in item.decorator_list)
    }
    assert "HINT" in property_names, (
        "PathBar.HINT 不再是 property——它会在 import 时被求值并冻结，"
        "于是语言切换后提示语不会跟着变（用户报过这个现象）")

    # 顺带守住：不许再出现"类属性形式的 HINT"
    for item in path_bar.body:
        if isinstance(item, ast.Assign):
            for target in item.targets:
                assert not (isinstance(target, ast.Name)
                            and target.id == "HINT"), (
                    "PathBar 里又出现了 HINT 的类属性赋值——"
                    "它会在 import 时求值")
