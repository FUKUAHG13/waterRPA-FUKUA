"""Central log presets, categories, and custom filtering policy."""

from __future__ import annotations

import json
from dataclasses import dataclass


LOG_CRITICAL = "critical"
LOG_RUN = "run"
LOG_STEP = "step"
LOG_FLOW = "flow"
LOG_ACTION = "action"
LOG_RECOGNITION = "recognition"
LOG_COORDINATES = "coordinates"
LOG_PARAMETERS = "parameters"
LOG_TIMING = "timing"
LOG_BACKEND = "backend"
LOG_ADAPTIVE = "adaptive"
LOG_APPLICATION = "application"
LOG_TIMESTAMP = "timestamp"


@dataclass(frozen=True)
class LogCategorySpec:
    key: str
    label: str
    description: str


LOG_CATEGORY_SPECS = (
    LogCategorySpec(LOG_RUN, "运行开始、结束与循环进度", "脚本启动、结束和循环范围信息"),
    LogCategorySpec(LOG_STEP, "步骤结果", "每一步成功、失败、跳过及耗时结果"),
    LogCategorySpec(LOG_FLOW, "流程分支与跳转", "成功/失败分支、循环跳转和条件流程"),
    LogCategorySpec(LOG_ACTION, "动作细节", "鼠标、键盘、等待、提醒和变量动作"),
    LogCategorySpec(LOG_RECOGNITION, "识别结果", "目标命中、未命中、倍率和相似度"),
    LogCategorySpec(LOG_COORDINATES, "坐标与点位", "实际坐标、点位序列和偏移状态"),
    LogCategorySpec(LOG_PARAMETERS, "运行与步骤参数", "完全调试使用的配置和步骤参数快照"),
    LogCategorySpec(LOG_TIMING, "耗时与性能", "识别、截图、匹配、点击和总体性能"),
    LogCategorySpec(LOG_BACKEND, "底层核心、缓存与回退", "原生 DLL、OpenCV、截图后端和缓存状态"),
    LogCategorySpec(LOG_ADAPTIVE, "画面唤醒与缩放记忆", "变化唤醒、自适应等待和常用倍率学习"),
    LogCategorySpec(LOG_APPLICATION, "设置、方案与按键映射", "主界面产生的设置和工具事件"),
    LogCategorySpec(LOG_TIMESTAMP, "界面本地时间", "界面日志显示毫秒时间；文件日志始终带时间"),
)

LOG_CATEGORY_KEYS = tuple(spec.key for spec in LOG_CATEGORY_SPECS)
LOG_CATEGORY_BY_KEY = {spec.key: spec for spec in LOG_CATEGORY_SPECS}

LOG_MODE_SIMPLE = "simple"
LOG_MODE_DETAILED = "detailed"
LOG_MODE_COMPLETE = "complete"
LOG_MODE_CUSTOM = "custom"
LOG_MODES = (
    LOG_MODE_SIMPLE,
    LOG_MODE_DETAILED,
    LOG_MODE_COMPLETE,
    LOG_MODE_CUSTOM,
)
LOG_MODE_LABELS = {
    LOG_MODE_SIMPLE: "简易",
    LOG_MODE_DETAILED: "详细",
    LOG_MODE_COMPLETE: "完全",
    LOG_MODE_CUSTOM: "自定义",
}
LOG_MODE_LEVELS = {
    LOG_MODE_SIMPLE: 0,
    LOG_MODE_DETAILED: 1,
    LOG_MODE_COMPLETE: 2,
    LOG_MODE_CUSTOM: 2,
}

SIMPLE_LOG_CATEGORIES = (
    LOG_RUN,
    LOG_STEP,
    LOG_FLOW,
    LOG_APPLICATION,
)
DETAILED_LOG_CATEGORIES = (
    LOG_RUN,
    LOG_STEP,
    LOG_FLOW,
    LOG_ACTION,
    LOG_RECOGNITION,
    LOG_COORDINATES,
    LOG_TIMING,
    LOG_APPLICATION,
    LOG_TIMESTAMP,
)
COMPLETE_LOG_CATEGORIES = (
    LOG_RUN,
    LOG_STEP,
    LOG_FLOW,
    LOG_ACTION,
    LOG_RECOGNITION,
    LOG_COORDINATES,
    LOG_PARAMETERS,
    LOG_TIMING,
    LOG_BACKEND,
    LOG_ADAPTIVE,
    LOG_APPLICATION,
    LOG_TIMESTAMP,
)
PRESET_LOG_CATEGORIES = {
    LOG_MODE_SIMPLE: SIMPLE_LOG_CATEGORIES,
    LOG_MODE_DETAILED: DETAILED_LOG_CATEGORIES,
    LOG_MODE_COMPLETE: COMPLETE_LOG_CATEGORIES,
}
DEFAULT_CUSTOM_LOG_CATEGORIES = DETAILED_LOG_CATEGORIES


def log_mode_from_level(level):
    try:
        numeric = int(level)
    except (TypeError, ValueError):
        numeric = 0
    return {
        0: LOG_MODE_SIMPLE,
        1: LOG_MODE_DETAILED,
        2: LOG_MODE_COMPLETE,
    }.get(numeric, LOG_MODE_SIMPLE)


def normalize_log_mode(value, legacy_level=0):
    text = str(value or "").strip().lower()
    aliases = {
        "简易": LOG_MODE_SIMPLE,
        "详细": LOG_MODE_DETAILED,
        "完全": LOG_MODE_COMPLETE,
        "自定义": LOG_MODE_CUSTOM,
    }
    if text in LOG_MODES:
        return text
    if str(value or "").strip() in aliases:
        return aliases[str(value).strip()]
    return log_mode_from_level(legacy_level)


def normalize_log_categories(value, fallback=DEFAULT_CUSTOM_LOG_CATEGORIES):
    raw = value
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raw = []
        elif text.startswith("["):
            try:
                raw = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                raw = text.split(",")
        else:
            raw = text.split(",")
    if not isinstance(raw, (list, tuple, set, frozenset)):
        raw = fallback
    selected = {str(item).strip() for item in raw}
    return tuple(key for key in LOG_CATEGORY_KEYS if key in selected)


def categories_for_mode(mode, custom_categories=DEFAULT_CUSTOM_LOG_CATEGORIES):
    normalized_mode = normalize_log_mode(mode)
    if normalized_mode == LOG_MODE_CUSTOM:
        return normalize_log_categories(custom_categories)
    return PRESET_LOG_CATEGORIES[normalized_mode]


def looks_critical(message):
    text = str(message or "")
    return any(
        token in text
        for token in (
            "严重崩溃",
            "执行线程异常",
            "引擎异常",
            "[错误]",
            "[超时急停]",
            "急停",
            "模板无法安全识别",
        )
    )


@dataclass(frozen=True)
class LogPolicy:
    mode: str = LOG_MODE_SIMPLE
    custom_categories: tuple[str, ...] = DEFAULT_CUSTOM_LOG_CATEGORIES

    @classmethod
    def create(cls, mode, custom_categories=DEFAULT_CUSTOM_LOG_CATEGORIES):
        return cls(
            normalize_log_mode(mode),
            normalize_log_categories(custom_categories),
        )

    @classmethod
    def from_legacy_level(cls, level):
        return cls.create(log_mode_from_level(level))

    @property
    def enabled_categories(self):
        return categories_for_mode(self.mode, self.custom_categories)

    @property
    def generation_level(self):
        return LOG_MODE_LEVELS[self.mode]

    @property
    def timestamp_enabled(self):
        return LOG_TIMESTAMP in self.enabled_categories

    @property
    def full_diagnostics(self):
        return self.mode in (LOG_MODE_COMPLETE, LOG_MODE_CUSTOM)

    def allows(self, category, *, critical=False, message=""):
        if critical or category == LOG_CRITICAL or looks_critical(message):
            return True
        normalized = str(category or LOG_ACTION)
        return normalized in self.enabled_categories

    def allows_verbose(self, category, *, critical=False, message=""):
        return self.full_diagnostics and self.allows(
            category, critical=critical, message=message
        )

    def enabled_labels(self):
        enabled = set(self.enabled_categories)
        return tuple(
            spec.label for spec in LOG_CATEGORY_SPECS if spec.key in enabled
        )
