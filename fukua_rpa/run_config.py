"""Validated immutable runtime settings and task snapshots."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .task_model import config_bool
from .scale_memory import (
    MAX_HISTORY_LIMIT,
    MAX_LEARNED_PREFERRED,
    MIN_HISTORY_LIMIT,
    SCALE_MEMORY_TIERS,
    parse_manual_scales,
)
from .workflow_document import materialize_runtime_references
from .scene_wake import SCENE_WAKE_SENSITIVITIES
from .vision import build_scale_values
from .log_policy import (
    LOG_MODES,
    LOG_MODE_LEVELS,
    normalize_log_categories,
    normalize_log_mode,
)


class RunConfigError(ValueError):
    pass


def _number(
    label: str,
    raw: Any,
    minimum: float | None = None,
    maximum: float | None = None,
    *,
    integer: bool = False,
    strictly_positive: bool = False,
) -> float | int:
    text = str(raw).strip()
    try:
        value = float(text)
    except (TypeError, ValueError) as error:
        raise RunConfigError(f"设置里的“{label}”必须是数字！\n填入内容: {text}") from error
    if not math.isfinite(value):
        raise RunConfigError(f"设置里的“{label}”必须是有限数字！\n填入内容: {text}")
    if integer and not value.is_integer():
        raise RunConfigError(f"设置里的“{label}”必须是整数！\n填入内容: {text}")
    if strictly_positive and value <= 0:
        raise RunConfigError(f"设置里的“{label}”必须大于 0！\n填入内容: {text}")
    if minimum is not None and value < minimum:
        raise RunConfigError(f"设置里的“{label}”不能小于 {minimum:g}！\n填入内容: {text}")
    if maximum is not None and value > maximum:
        raise RunConfigError(f"设置里的“{label}”不能大于 {maximum:g}！\n填入内容: {text}")
    return int(value) if integer else value


@dataclass(frozen=True)
class EngineRunConfig:
    confidence: float
    min_scale: float
    max_scale: float
    scale_step: float
    enable_grayscale: bool
    use_native_core: bool
    native_parallel_mode: str
    use_native_scale_hint: bool
    scale_memory_tier: str
    scale_memory_manual: tuple[float, ...]
    scale_memory_custom_enabled: bool
    scale_memory_preferred_limit: int
    scale_memory_history_limit: int
    dodge_x1: int
    dodge_y1: int
    dodge_x2: int
    dodge_y2: int
    enable_dodge: bool
    enable_double_dodge: bool
    double_dodge_wait: float
    dodge_click_action: str
    move_duration: float
    click_hold: float
    settlement_wait: float
    timeout_val: float
    timeout_stop: bool
    detect_delay: float
    adaptive_backoff: bool
    scene_wake_enabled: bool
    scene_wake_sensitivity: str
    show_click_indicator: bool
    playback_speed: float
    start_step_index: int
    loop_start_round: int
    loop_end_round: int
    multi_target_mode: str
    multi_target_order: str
    loop_mode: str
    loop_val: float
    log_level: int
    log_mode: str
    log_custom_categories: tuple[str, ...]
    enable_tm_stop: bool
    enable_tr_stop: bool
    enable_key_stop: bool

    @classmethod
    def from_mapping(
        cls, config: Mapping[str, Any], task_count: int | None = None
    ) -> "EngineRunConfig":
        if not isinstance(config, Mapping):
            raise RunConfigError("运行配置不是有效的配置对象")
        confidence = float(_number("全局相似度", config.get("conf", "0.8"), 0.05, 1.0))
        min_scale = float(_number("最小缩放", config.get("scale_min", "0.8"), 0.01, 5.0))
        max_scale = float(_number("最大缩放", config.get("scale_max", "1.2"), 0.01, 5.0))
        scale_step = float(
            _number("缩放步长", config.get("scale_step", "0.05"), strictly_positive=True)
        )
        try:
            build_scale_values(min_scale, max_scale, scale_step)
        except ValueError as error:
            raise RunConfigError(f"全局缩放设置无效：{error}") from error

        move_duration = float(_number("移动耗时", config.get("move_spd", "0"), 0.0, 60.0))
        click_hold = float(_number("按住时长", config.get("click_hld", "0.04"), 0.0, 10.0))
        settlement_wait = float(_number("步间隔", config.get("settle", "0.5"), 0.0))
        timeout_val = float(_number("单步超时", config.get("timeout", "0"), 0.0))
        detect_delay = float(_number("识别频率", config.get("detect_delay", "0.1"), 0.0, 60.0))
        double_dodge_wait = float(
            _number("二段避让间隔", config.get("dbl_wait", "0.015"), 0.0, 60.0)
        )
        playback_speed = float(
            _number("倍速执行", config.get("playback_speed", "1"), maximum=100.0, strictly_positive=True)
        )
        dodge_x1 = int(_number("避让坐标1 X", config.get("dodge_x1", "100"), integer=True))
        dodge_y1 = int(_number("避让坐标1 Y", config.get("dodge_y1", "100"), integer=True))
        dodge_x2 = int(_number("避让坐标2 X", config.get("dodge_x2", "200"), integer=True))
        dodge_y2 = int(_number("避让坐标2 Y", config.get("dodge_y2", "100"), integer=True))
        dodge_click_action = str(
            config.get("dodge_click_action", "none")
        ).strip().lower()
        if dodge_click_action not in ("none", "left", "right"):
            raise RunConfigError(
                f"设置里的“避让后操作”无效：{dodge_click_action}"
            )

        loop_mode = str(config.get("loop_mode", "单次"))
        valid_loop_modes = {
            "单次",
            "无限",
            "指定次数",
            "指定时间(时)",
            "指定时间(分)",
            "指定时间(秒)",
        }
        if loop_mode not in valid_loop_modes:
            raise RunConfigError(f"设置里的“循环模式”无效：{loop_mode}")
        loop_val = 1.0
        if loop_mode == "指定次数":
            loop_val = float(
                _number("循环次数", config.get("loop_val", "1"), integer=True, strictly_positive=True)
            )
        elif loop_mode in ("指定时间(时)", "指定时间(分)", "指定时间(秒)"):
            loop_val = float(
                _number("运行时间", config.get("loop_val", "1"), strictly_positive=True)
            )
        else:
            try:
                loop_val = float(config.get("loop_val", 1.0))
            except (TypeError, ValueError):
                loop_val = 1.0

        start_step = int(_number("从第X步开始执行", config.get("start_step", "1"), 1, integer=True))
        if task_count is not None and task_count > 0 and start_step > task_count:
            raise RunConfigError(
                f"设置里的'从第X步开始执行'必须是 1 到 {task_count} 之间的整数！\n"
                f"填入内容: {start_step}"
            )
        loop_start_round = int(
            _number("脚本从第X次循环开始", config.get("loop_start_round", "1"), 1, integer=True)
        )
        loop_end_round = int(
            _number("到第X次循环停止", config.get("loop_end_round", "0"), 0, integer=True)
        )
        if loop_end_round > 0 and loop_end_round < loop_start_round:
            raise RunConfigError(
                "设置里的'到第X次循环停止'不能小于起始循环！\n"
                f"起始循环: {loop_start_round}，停止循环: {loop_end_round}"
            )
        if loop_mode == "单次" and loop_start_round > 1:
            raise RunConfigError(
                "当前是'单次'循环模式，脚本起始循环必须为 1；如果要从第多次循环开始，"
                "请把循环模式改为'无限'或'指定次数'。"
            )

        multi_target_mode = str(config.get("multi_target_mode", "快速一个"))
        if multi_target_mode == "最佳一个":
            multi_target_mode = "快速一个"
        if multi_target_mode not in ("快速一个", "全部匹配"):
            raise RunConfigError(f"设置里的“多目标模式”无效：{multi_target_mode}")
        multi_target_order = str(config.get("multi_target_order", "从上到下"))
        if multi_target_order not in (
            "从上到下",
            "从左到右",
            "从右到左",
            "距离鼠标最近优先",
            "随机顺序",
        ):
            raise RunConfigError(f"设置里的“多目标顺序”无效：{multi_target_order}")
        log_level = int(
            _number("日志级别", config.get("log_level", 0), 0, 2, integer=True)
        )
        raw_log_mode = config.get("log_mode")
        if raw_log_mode is not None:
            raw_log_mode_text = str(raw_log_mode).strip().lower()
            if raw_log_mode_text not in LOG_MODES and str(raw_log_mode).strip() not in (
                "简易",
                "详细",
                "完全",
                "自定义",
            ):
                raise RunConfigError(f"设置里的“日志模式”无效：{raw_log_mode}")
        log_mode = normalize_log_mode(raw_log_mode, log_level)
        log_custom_categories = normalize_log_categories(
            config.get("log_custom_categories")
        )
        log_level = LOG_MODE_LEVELS[log_mode]
        native_parallel_mode = str(
            config.get("native_parallel_mode", "auto")
        ).strip().lower()
        if native_parallel_mode not in ("off", "auto", "force"):
            raise RunConfigError(
                f"设置里的“原生多核模式”无效：{native_parallel_mode}"
            )
        scale_memory_tier = str(
            config.get("scale_memory_tier", "balanced")
        ).strip().lower()
        if scale_memory_tier not in SCALE_MEMORY_TIERS:
            raise RunConfigError(
                f"设置里的“缩放记忆策略”无效：{scale_memory_tier}"
            )
        try:
            scale_memory_manual = parse_manual_scales(
                config.get("scale_memory_manual", "")
            )
        except ValueError as error:
            raise RunConfigError(f"手动优先倍率无效：{error}") from error
        scale_memory_custom_enabled = config_bool(
            config.get("scale_memory_custom_en", False)
        )
        scale_memory_preferred_limit = int(
            _number(
                "学习优先倍率上限",
                config.get("scale_memory_preferred_limit", 3),
                1,
                MAX_LEARNED_PREFERRED,
                integer=True,
            )
        )
        scale_memory_history_limit = int(
            _number(
                "缩放历史记录上限",
                config.get("scale_memory_history_limit", 64),
                MIN_HISTORY_LIMIT,
                MAX_HISTORY_LIMIT,
                integer=True,
            )
        )
        scene_wake_sensitivity = str(
            config.get("scene_wake_sensitivity", "balanced")
        ).strip().lower()
        if scene_wake_sensitivity not in SCENE_WAKE_SENSITIVITIES:
            raise RunConfigError(
                f"设置里的“画面变化灵敏度”无效：{scene_wake_sensitivity}"
            )

        return cls(
            confidence=confidence,
            min_scale=min_scale,
            max_scale=max_scale,
            scale_step=scale_step,
            enable_grayscale=config_bool(config.get("gray_en", True)),
            use_native_core=config_bool(config.get("native_core_en", True)),
            native_parallel_mode=native_parallel_mode,
            use_native_scale_hint=config_bool(
                config.get("native_scale_hint_en", True)
            ),
            scale_memory_tier=scale_memory_tier,
            scale_memory_manual=scale_memory_manual,
            scale_memory_custom_enabled=scale_memory_custom_enabled,
            scale_memory_preferred_limit=scale_memory_preferred_limit,
            scale_memory_history_limit=scale_memory_history_limit,
            dodge_x1=dodge_x1,
            dodge_y1=dodge_y1,
            dodge_x2=dodge_x2,
            dodge_y2=dodge_y2,
            enable_dodge=config_bool(config.get("dodge_en", False)),
            enable_double_dodge=config_bool(config.get("dbl_dodge", False)),
            double_dodge_wait=double_dodge_wait,
            dodge_click_action=dodge_click_action,
            move_duration=move_duration,
            click_hold=click_hold,
            settlement_wait=settlement_wait,
            timeout_val=timeout_val,
            timeout_stop=config_bool(config.get("timeout_stop", False)),
            detect_delay=detect_delay,
            adaptive_backoff=config_bool(config.get("adaptive_backoff", True)),
            scene_wake_enabled=config_bool(
                config.get("scene_wake_en", True)
            ),
            scene_wake_sensitivity=scene_wake_sensitivity,
            show_click_indicator=config_bool(config.get("click_indicator", True)),
            playback_speed=playback_speed,
            start_step_index=start_step - 1,
            loop_start_round=loop_start_round,
            loop_end_round=loop_end_round,
            multi_target_mode=multi_target_mode,
            multi_target_order=multi_target_order,
            loop_mode=loop_mode,
            loop_val=loop_val,
            log_level=log_level,
            log_mode=log_mode,
            log_custom_categories=log_custom_categories,
            enable_tm_stop=config_bool(config.get("tm_fs", True)),
            enable_tr_stop=config_bool(config.get("tr_fs", True)),
            enable_key_stop=config_bool(config.get("key_fs", True)),
        )

    def apply_to(self, engine: Any) -> None:
        for field_name, engine_name in (
            ("confidence", "confidence"),
            ("min_scale", "min_scale"),
            ("max_scale", "max_scale"),
            ("scale_step", "scale_step"),
            ("enable_grayscale", "enable_grayscale"),
            ("use_native_core", "use_native_core"),
            ("native_parallel_mode", "native_parallel_mode"),
            ("use_native_scale_hint", "use_native_scale_hint"),
            ("scale_memory_tier", "scale_memory_tier"),
            ("scale_memory_manual", "scale_memory_manual"),
            ("scale_memory_custom_enabled", "scale_memory_custom_enabled"),
            ("scale_memory_preferred_limit", "scale_memory_preferred_limit"),
            ("scale_memory_history_limit", "scale_memory_history_limit"),
            ("dodge_x1", "dodge_x1"),
            ("dodge_y1", "dodge_y1"),
            ("dodge_x2", "dodge_x2"),
            ("dodge_y2", "dodge_y2"),
            ("enable_dodge", "enable_dodge"),
            ("enable_double_dodge", "enable_double_dodge"),
            ("double_dodge_wait", "double_dodge_wait"),
            ("dodge_click_action", "dodge_click_action"),
            ("move_duration", "move_duration"),
            ("click_hold", "click_hold"),
            ("settlement_wait", "settlement_wait"),
            ("timeout_val", "timeout_val"),
            ("timeout_stop", "timeout_stop"),
            ("detect_delay", "detect_delay"),
            ("adaptive_backoff", "adaptive_backoff"),
            ("scene_wake_enabled", "scene_wake_enabled"),
            ("scene_wake_sensitivity", "scene_wake_sensitivity"),
            ("show_click_indicator", "show_click_indicator"),
            ("playback_speed", "playback_speed"),
            ("start_step_index", "start_step_index"),
            ("loop_start_round", "loop_start_round"),
            ("loop_end_round", "loop_end_round"),
            ("multi_target_mode", "multi_target_mode"),
            ("multi_target_order", "multi_target_order"),
            ("loop_mode", "loop_mode"),
            ("loop_val", "loop_val"),
            ("enable_tm_stop", "enable_tm_stop"),
            ("enable_tr_stop", "enable_tr_stop"),
            ("enable_key_stop", "enable_key_stop"),
        ):
            setattr(engine, engine_name, getattr(self, field_name))
        engine.configure_log_policy(self.log_mode, self.log_custom_categories)
        engine.use_fast_screenshot = True


@dataclass(frozen=True)
class RunRequest:
    """A detached runtime snapshot; later UI edits cannot mutate this run."""

    tasks: tuple[dict[str, Any], ...]
    config: EngineRunConfig
    profile_name: str

    @classmethod
    def create(
        cls,
        tasks: Sequence[Mapping[str, Any]],
        config: Mapping[str, Any],
        profile_name: str,
    ) -> "RunRequest":
        detached = tuple(materialize_runtime_references(tasks))
        return cls(
            tasks=detached,
            config=EngineRunConfig.from_mapping(config, len(detached)),
            profile_name=str(profile_name),
        )

    def mutable_tasks(self) -> list[dict[str, Any]]:
        return copy.deepcopy(list(self.tasks))
