"""Single source of truth for persisted command IDs and user-facing names."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    TASK_TYPE_ACTIVATE_WINDOW,
    TASK_TYPE_CLOSE_WINDOW,
    TASK_TYPE_EXPRESSION,
    TASK_TYPE_LAUNCH_APP,
    TASK_TYPE_SECRET_TEXT,
    TASK_TYPE_SET_VARIABLE,
    TASK_TYPE_UIA_CLICK,
    TASK_TYPE_UIA_READ_VALUE,
    TASK_TYPE_UIA_SET_VALUE,
    TASK_TYPE_UNTIL,
    TASK_TYPE_WAIT_WINDOW,
)


@dataclass(frozen=True)
class CommandSpec:
    code: float
    name: str
    category: str
    accepts_coordinate: bool = False
    accepts_image: bool = False


COMMAND_SPECS = (
    CommandSpec(1.0, "左键单击", "mouse", True, True),
    CommandSpec(2.0, "左键双击", "mouse", True, True),
    CommandSpec(3.0, "右键单击", "mouse", True, True),
    CommandSpec(4.0, "输入文本", "keyboard"),
    CommandSpec(5.0, "等待(秒)", "flow"),
    CommandSpec(6.0, "滚轮滑动", "mouse"),
    CommandSpec(7.0, "系统按键", "keyboard"),
    CommandSpec(8.0, "鼠标悬停", "mouse", True, True),
    CommandSpec(9.0, "截图保存", "capture"),
    CommandSpec(10.0, "左键拖拽", "mouse"),
    CommandSpec(11.0, "右键拖拽", "mouse"),
    CommandSpec(12.0, "弹窗提醒", "notification"),
    CommandSpec(13.0, "停止运行", "flow"),
    CommandSpec(14.0, "声音提示", "notification"),
    CommandSpec(TASK_TYPE_UNTIL, "直到条件成立", "flow"),
    CommandSpec(TASK_TYPE_SET_VARIABLE, "设置变量", "flow"),
    CommandSpec(TASK_TYPE_EXPRESSION, "判断表达式", "flow"),
    CommandSpec(TASK_TYPE_LAUNCH_APP, "启动程序", "window"),
    CommandSpec(TASK_TYPE_WAIT_WINDOW, "等待窗口", "window"),
    CommandSpec(TASK_TYPE_ACTIVATE_WINDOW, "激活窗口", "window"),
    CommandSpec(TASK_TYPE_CLOSE_WINDOW, "关闭窗口", "window"),
    CommandSpec(TASK_TYPE_SECRET_TEXT, "输入秘密文本", "keyboard"),
    CommandSpec(TASK_TYPE_UIA_CLICK, "点击窗口控件", "window"),
    CommandSpec(TASK_TYPE_UIA_SET_VALUE, "设置控件文本", "window"),
    CommandSpec(TASK_TYPE_UIA_READ_VALUE, "读取控件文本", "window"),
)

COMMAND_BY_CODE = {spec.code: spec for spec in COMMAND_SPECS}
COMMAND_BY_NAME = {spec.name: spec for spec in COMMAND_SPECS}
CLICK_COMMANDS = frozenset({1.0, 2.0, 3.0})
IMAGE_TARGET_COMMANDS = frozenset(
    spec.code for spec in COMMAND_SPECS if spec.accepts_image
)
COORDINATE_TARGET_COMMANDS = frozenset(
    spec.code for spec in COMMAND_SPECS if spec.accepts_coordinate
)
DRAG_COMMANDS = frozenset({10.0, 11.0})


def command_name(code, default="未知操作"):
    try:
        normalized = float(code)
    except (TypeError, ValueError):
        return default
    spec = COMMAND_BY_CODE.get(normalized)
    return spec.name if spec else default


def command_code(name, default=1.0):
    spec = COMMAND_BY_NAME.get(str(name))
    return spec.code if spec else float(default)


def command_names():
    return [spec.name for spec in COMMAND_SPECS]
