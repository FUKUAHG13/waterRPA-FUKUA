"""UI-independent validation for executable task lists."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from typing import Any

from .constants import (
    MAX_SINGLE_TEMPLATE_CACHE_BYTES,
    MAX_TEMPLATE_CACHE_BYTES,
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
    UNTIL_CONDITION_LOGICS,
    UNTIL_LIMIT_ACTIONS,
)
from .commands import COMMAND_BY_CODE
from .expressions import (
    ExpressionError,
    compile_expression,
    parse_assignment,
    validate_variable_name,
)
from .run_config import EngineRunConfig, RunConfigError
from .task_model import (
    config_bool,
    parse_coordinate_sequence,
    parse_coordinate_text,
    parse_region_text,
    until_condition_list_from_data,
)
from .vision import build_scale_values, estimate_template_cache_bytes, template_detail_status


class TaskListValidator:
    def __init__(self, config: Mapping[str, Any]):
        self.config = config
        self.estimated_cache_total = 0
        self.estimated_cache_keys: set[tuple] = set()

    def _add_template_budget(
        self, path: str, use_gray: bool, scale_values: Sequence[float], step_no: int
    ) -> str | None:
        key = (os.path.abspath(path), bool(use_gray), tuple(scale_values))
        if key in self.estimated_cache_keys:
            return None
        self.estimated_cache_keys.add(key)
        try:
            estimated = estimate_template_cache_bytes(path, use_gray, scale_values)
        except ValueError as error:
            return f"第 {step_no} 步模板无法读取：{error}"
        if estimated > MAX_SINGLE_TEMPLATE_CACHE_BYTES:
            return (
                f"第 {step_no} 步图片预计需要 {estimated / 1024 / 1024:.1f} MB 模板缓存，"
                f"超过单图上限 {MAX_SINGLE_TEMPLATE_CACHE_BYTES / 1024 / 1024:.0f} MB。\n"
                "请缩小模板图片或缩放范围。"
            )
        self.estimated_cache_total += estimated
        if self.estimated_cache_total > MAX_TEMPLATE_CACHE_BYTES:
            return (
                f"全部图片预计需要超过 {MAX_TEMPLATE_CACHE_BYTES / 1024 / 1024:.0f} MB 模板缓存。\n"
                "请减少图片数量、缩放范围或缩放档位。"
            )
        return None

    def validate(self, tasks: Sequence[Mapping[str, Any]]) -> str | None:
        if not tasks:
            return "脚本中没有可执行步骤。"
        try:
            run_config = EngineRunConfig.from_mapping(self.config, len(tasks))
        except RunConfigError as error:
            return str(error)

        global_scale_values = build_scale_values(
            run_config.min_scale, run_config.max_scale, run_config.scale_step
        )
        global_use_gray = run_config.enable_grayscale

        for index, task in enumerate(tasks):
            step_no = index + 1
            if not isinstance(task, Mapping):
                return f"第 {step_no} 步不是有效的步骤对象。"
            error = self._validate_task(
                task,
                step_no,
                len(tasks),
                global_scale_values,
                global_use_gray,
                run_config.confidence,
            )
            if error:
                return error
        return None

    def _validate_task(
        self,
        task: Mapping[str, Any],
        step_no: int,
        task_count: int,
        global_scale_values: Sequence[float],
        global_use_gray: bool,
        global_confidence: float,
    ) -> str | None:
        raw_task_type = task.get("type")
        try:
            task_type = float(raw_task_type)
        except (TypeError, ValueError):
            return f"第 {step_no} 步的指令类型无效：{raw_task_type}"
        if task_type not in COMMAND_BY_CODE:
            return f"第 {step_no} 步使用了未注册的指令类型：{raw_task_type}"
        value = str(task.get("value", "")).strip()
        success_skip = str(task.get("success_skip", "0")).strip()
        success_jump = str(task.get("success_jump", "0")).strip()
        fail_skip = str(task.get("fail_skip", "0")).strip()
        fail_jump = str(task.get("fail_jump", "0")).strip()
        repeat_mode = str(task.get("repeat_mode", "执行一次"))
        repeat_count = str(task.get("repeat_count", "1")).strip()
        step_loop_start = str(task.get("step_loop_start", "1")).strip()
        step_loop_end = str(task.get("step_loop_end", "0")).strip()
        fail_limit = str(task.get("fail_limit", "1")).strip()
        point_limit_count = str(task.get("point_limit_count", "0")).strip()
        image_click_point_en = config_bool(task.get("image_click_point_en", False))
        image_click_point_rx = str(task.get("image_click_point_rx", "0.5")).strip()
        image_click_point_ry = str(task.get("image_click_point_ry", "0.5")).strip()
        step_region_en = config_bool(task.get("step_region_en", False))
        step_region = str(task.get("step_region", "")).strip()
        coord_step_en = config_bool(task.get("coord_step_en", False))
        coord_step_every = str(task.get("coord_step_every", "1")).strip()
        coord_step_direction = str(task.get("coord_step_direction", "向下")).strip()
        coord_step_distance = str(task.get("coord_step_distance", "0")).strip()
        coord_step_dx = str(task.get("coord_step_dx", "0")).strip()
        coord_step_dy = str(task.get("coord_step_dy", "0")).strip()
        coord_step_point = str(task.get("coord_step_point", "")).strip()
        coord_step_max_steps = str(task.get("coord_step_max_steps", "0")).strip()
        coord_step_max_distance = str(task.get("coord_step_max_distance", "0")).strip()
        coord_step_reset_after = str(task.get("coord_step_reset_after", "0")).strip()
        coord_sequence_en = config_bool(task.get("coord_sequence_en", False))
        coord_sequence_points = str(task.get("coord_sequence_points", "")).strip()
        coord_sequence_end_action = str(
            task.get("coord_sequence_end_action", "点完后跳过本步")
        ).strip()
        run_max_executions = str(task.get("run_max_executions", "0")).strip()
        debug_breakpoint = config_bool(task.get("debug_breakpoint", False))
        debug_condition = str(task.get("debug_condition", "") or "").strip()

        if debug_breakpoint and debug_condition:
            try:
                compile_expression(debug_condition)
            except ExpressionError as error:
                return f"第 {step_no} 步小齿轮里的'断点条件'无效：{error}"

        if success_skip and not success_skip.isdigit():
            return f"第 {step_no} 步小齿轮里的'成功后跳过'必须是整数！\n填入内容: {success_skip}"
        if fail_skip and not fail_skip.isdigit():
            return f"第 {step_no} 步小齿轮里的'失败后跳过'必须是整数！\n填入内容: {fail_skip}"
        if success_jump and (not success_jump.isdigit() or int(success_jump) > task_count):
            return f"第 {step_no} 步小齿轮里的'成功后跳至'必须是 0 到 {task_count} 之间的整数！\n填入内容: {success_jump}"
        if fail_jump and (not fail_jump.isdigit() or int(fail_jump) > task_count):
            return f"第 {step_no} 步小齿轮里的'失败后跳至'必须是 0 到 {task_count} 之间的整数！\n填入内容: {fail_jump}"
        if fail_limit and (not fail_limit.isdigit() or int(fail_limit) < 1):
            return f"第 {step_no} 步小齿轮里的'连续失败次数'必须是大于等于 1 的整数！\n填入内容: {fail_limit}"
        if repeat_mode == "指定次数" and (not repeat_count.isdigit() or int(repeat_count) < 1):
            return f"第 {step_no} 步小齿轮里的'重复次数'必须是大于等于 1 的整数！\n填入内容: {repeat_count}"
        if run_max_executions and (
            not run_max_executions.isdigit() or int(run_max_executions) < 0
        ):
            return f"第 {step_no} 步小齿轮里的'本次运行最多执行'必须是大于等于 0 的整数！\n填入内容: {run_max_executions}"
        if not step_loop_start.isdigit() or int(step_loop_start) < 1:
            return f"第 {step_no} 步小齿轮里的'循环范围起始'必须是大于等于 1 的整数！\n填入内容: {step_loop_start}"
        if not step_loop_end.isdigit() or int(step_loop_end) < 0:
            return f"第 {step_no} 步小齿轮里的'循环范围停止'必须是大于等于 0 的整数！\n填入内容: {step_loop_end}"
        if int(step_loop_end) > 0 and int(step_loop_end) < int(step_loop_start):
            return f"第 {step_no} 步小齿轮里的'循环范围停止'不能小于起始循环！\n起始循环: {step_loop_start}，停止循环: {step_loop_end}"
        if point_limit_count and not point_limit_count.isdigit():
            return f"第 {step_no} 步小齿轮里的'同点点击上限'必须是大于等于 0 的整数！\n填入内容: {point_limit_count}"

        coordinate = parse_coordinate_text(value)
        if image_click_point_en:
            if task_type not in (1.0, 2.0, 3.0) or coordinate or not os.path.isfile(value):
                return f"第 {step_no} 步小齿轮里的'图片内点击点'仅能用于左键/右键图片点击步骤，且参数必须是存在的图片路径。\n填入内容: {value}"
            try:
                rx = float(image_click_point_rx)
                ry = float(image_click_point_ry)
                if not (0.0 <= rx <= 1.0 and 0.0 <= ry <= 1.0):
                    raise ValueError
            except (TypeError, ValueError):
                return f"第 {step_no} 步小齿轮里的'图片内点击点'相对位置必须是 0 到 1 之间的数字！\n填入内容: X={image_click_point_rx}, Y={image_click_point_ry}"
        if step_region_en:
            if task_type not in (1.0, 2.0, 3.0, 8.0) or coordinate:
                return f"第 {step_no} 步小齿轮里的'本步识别区域'仅能用于图片点击/图片悬停步骤。"
            if not parse_region_text(step_region):
                return f"第 {step_no} 步小齿轮里的'本步识别区域'格式错误，应为 x,y,w,h！\n填入内容: {step_region}"

        if coord_step_en and task_type in (1.0, 2.0, 3.0) and coordinate:
            error = self._validate_coordinate_step(
                step_no,
                coord_step_every,
                coord_step_direction,
                coord_step_distance,
                coord_step_dx,
                coord_step_dy,
                coord_step_point,
                coord_step_max_steps,
                coord_step_max_distance,
                coord_step_reset_after,
            )
            if error:
                return error

        if coord_sequence_en:
            if task_type not in (1.0, 2.0, 3.0) or not coordinate:
                return f"第 {step_no} 步小齿轮里的'自定义点位'仅能用于直接坐标的左键/右键点击步骤。"
            if coord_sequence_end_action not in (
                "点完后跳过本步",
                "点完后停在最后一个",
                "点完后循环",
            ):
                return f"第 {step_no} 步小齿轮里的'自定义点位结束后'设置无效！\n填入内容: {coord_sequence_end_action}"
            if not parse_coordinate_sequence(coord_sequence_points):
                return f"第 {step_no} 步小齿轮里的'自定义点位'至少要包含一个 x,y 坐标！\n填入内容: {coord_sequence_points}"

        if task_type == TASK_TYPE_UNTIL:
            return self._validate_until_task(
                task, step_no, task_count, global_scale_values, global_use_gray
            )

        if task_type == TASK_TYPE_SET_VARIABLE:
            try:
                parse_assignment(value)
            except ExpressionError as error:
                return f"第 {step_no} 步【设置变量】无效：{error}"
            return None

        if task_type == TASK_TYPE_EXPRESSION:
            try:
                compile_expression(value)
            except ExpressionError as error:
                return f"第 {step_no} 步【判断表达式】无效：{error}"
            return None

        if task_type in (
            TASK_TYPE_UIA_CLICK,
            TASK_TYPE_UIA_SET_VALUE,
            TASK_TYPE_UIA_READ_VALUE,
        ):
            binding = task.get("uia_binding")
            if not isinstance(binding, Mapping) or not binding:
                return f"第 {step_no} 步尚未选择目标窗口控件，请点击步骤右侧的“控”。"
            if task_type == TASK_TYPE_UIA_READ_VALUE:
                try:
                    validate_variable_name(value)
                except ExpressionError as error:
                    return f"第 {step_no} 步【读取控件文本】的变量名无效：{error}"
            return None

        if task_type == TASK_TYPE_SECRET_TEXT and not value:
            return f"第 {step_no} 步【输入秘密文本】必须填写凭据名称。"

        if task_type in (
            TASK_TYPE_LAUNCH_APP,
            TASK_TYPE_WAIT_WINDOW,
            TASK_TYPE_ACTIVATE_WINDOW,
            TASK_TYPE_CLOSE_WINDOW,
        ) and not value:
            return f"第 {step_no} 步参数不能为空！"

        if not value and task_type not in (12.0, 13.0, 14.0):
            return f"第 {step_no} 步参数不能为空！"
        if task_type in (1.0, 2.0, 3.0, 8.0) and not coordinate:
            if not os.path.isfile(value):
                return f"第 {step_no} 步找图错误：图片路径不存在或坐标格式错误 (坐标应为 x,y)\n填入内容: {value}"
            custom_enabled = config_bool(task.get("custom_en", False))
            try:
                task_confidence = (
                    float(task.get("custom_conf", global_confidence))
                    if custom_enabled
                    else global_confidence
                )
                if not math.isfinite(task_confidence) or not 0.05 <= task_confidence <= 1.0:
                    raise ValueError
            except (TypeError, ValueError):
                return f"第 {step_no} 步小齿轮里的独立相似度必须在 0.05 到 1.0 之间！"
            try:
                if custom_enabled:
                    scale_min = float(task.get("custom_scale_min", self.config.get("scale_min", "0.8")))
                    scale_max = float(task.get("custom_scale_max", self.config.get("scale_max", "1.2")))
                    scale_step = float(task.get("custom_scale_step", self.config.get("scale_step", "0.05")))
                    if scale_min < 0.01 or scale_max > 5.0:
                        raise ValueError("缩放范围必须在 0.01 到 5.0 之间")
                    scale_values = build_scale_values(scale_min, scale_max, scale_step)
                    use_gray = config_bool(task.get("custom_gray", global_use_gray))
                else:
                    scale_values = global_scale_values
                    use_gray = global_use_gray
            except (TypeError, ValueError) as error:
                return f"第 {step_no} 步小齿轮里的独立缩放设置无效：{error}"
            valid, reason = template_detail_status(value, use_gray)
            if not valid:
                return f"第 {step_no} 步模板无法安全识别：{reason}"
            return self._add_template_budget(value, use_gray, scale_values, step_no)
        if task_type == 9.0:
            if not os.path.isdir(value):
                extension = os.path.splitext(value)[1].lower()
                if extension not in (".png", ".jpg", ".jpeg", ".bmp"):
                    return f"第 {step_no} 步截图保存路径必须是已存在的文件夹，或以 .png/.jpg/.jpeg/.bmp 结尾的文件路径！\n填入内容: {value}"
                parent_dir = os.path.dirname(os.path.abspath(value))
                if not os.path.isdir(parent_dir):
                    return f"第 {step_no} 步截图保存目录不存在！\n目录: {parent_dir}"
        elif task_type in (10.0, 11.0):
            if "->" not in value:
                return f"第 {step_no} 步拖拽参数错误，需包含 '->' 符号，例如: 100,100 -> 200,200"
            parts = value.split("->")
            if len(parts) != 2 or not parse_coordinate_text(parts[0]) or not parse_coordinate_text(parts[1]):
                return f"第 {step_no} 步拖拽坐标格式异常，无法解析出首尾坐标！"
        elif task_type in (5.0, 6.0):
            try:
                number_value = float(value)
                if not math.isfinite(number_value) or (task_type == 5.0 and number_value < 0):
                    raise ValueError
            except (TypeError, ValueError):
                return f"第 {step_no} 步参数必须是有限数字，等待时间不能小于 0！"
        return None

    @staticmethod
    def _validate_coordinate_step(
        step_no: int,
        every: str,
        direction: str,
        distance: str,
        dx: str,
        dy: str,
        point: str,
        max_steps: str,
        max_distance: str,
        reset_after: str,
    ) -> str | None:
        if not every.isdigit() or int(every) < 1:
            return f"第 {step_no} 步小齿轮里的'步进频率'必须是大于等于 1 的整数！\n填入内容: {every}"
        if max_steps and (not max_steps.isdigit() or int(max_steps) < 0):
            return f"第 {step_no} 步小齿轮里的'最大偏移次数'必须是大于等于 0 的整数！\n填入内容: {max_steps}"
        if reset_after and (not reset_after.isdigit() or int(reset_after) < 0):
            return f"第 {step_no} 步小齿轮里的'重置循环'必须是大于等于 0 的整数！\n填入内容: {reset_after}"
        try:
            max_distance_value = float(max_distance or 0)
            if not math.isfinite(max_distance_value) or max_distance_value < 0:
                raise ValueError
        except (TypeError, ValueError):
            return f"第 {step_no} 步小齿轮里的'最大偏移距离'必须是大于等于 0 的数字！\n填入内容: {max_distance}"
        if direction in ("向上", "向下", "向左", "向右"):
            try:
                if not math.isfinite(float(distance)):
                    raise ValueError
            except (TypeError, ValueError):
                return f"第 {step_no} 步小齿轮里的'步进距离'必须是有限数字！\n填入内容: {distance}"
        elif direction == "自定义偏移":
            try:
                if not math.isfinite(float(dx)) or not math.isfinite(float(dy)):
                    raise ValueError
            except (TypeError, ValueError):
                return f"第 {step_no} 步小齿轮里的'自定义偏移 dx/dy'必须是数字！\n填入内容: dx={dx}, dy={dy}"
        elif direction == "移动到新点位":
            if not parse_coordinate_text(point):
                return f"第 {step_no} 步小齿轮里的'目标点位'必须是 x,y 坐标格式！\n填入内容: {point}"
            if int(max_steps or 0) == 1:
                return f"第 {step_no} 步小齿轮里的'移动上限'在移动到新点位时不能填 1。\n填 0 表示起点后直接移动到目标点；填 2 或更大表示从起点到目标点一共点击多少个点位。"
        else:
            return f"第 {step_no} 步小齿轮里的'步进方向'无效！\n填入内容: {direction}"
        return None

    def _validate_until_task(
        self,
        task: Mapping[str, Any],
        step_no: int,
        task_count: int,
        global_scale_values: Sequence[float],
        global_use_gray: bool,
    ) -> str | None:
        conditions = until_condition_list_from_data(task)
        if not conditions:
            return f"第 {step_no} 步【直到条件成立】至少要启用一个条件。"
        logic = str(task.get("until_logic", "全部满足"))
        if logic not in UNTIL_CONDITION_LOGICS:
            return f"第 {step_no} 步【直到条件成立】的条件关系无效：{logic}"
        action = str(task.get("until_on_limit", "继续下一步"))
        if action not in UNTIL_LIMIT_ACTIONS:
            return f"第 {step_no} 步【直到条件成立】的达到上限后处理方式无效：{action}"
        for key, label in (("until_false_jump", "未满足跳回"), ("until_true_jump", "满足后跳至")):
            raw = str(task.get(key, "0")).strip() or "0"
            if not raw.isdigit() or int(raw) > task_count:
                return f"第 {step_no} 步【直到条件成立】里的“{label}”必须是 0 到 {task_count} 之间的整数！\n填入内容: {raw}"
        max_checks = str(task.get("until_max_checks", "0")).strip() or "0"
        if not max_checks.isdigit() or int(max_checks) < 0:
            return f"第 {step_no} 步【直到条件成立】里的“最多检查次数”必须是大于等于 0 的整数！\n填入内容: {max_checks}"
        try:
            max_seconds = float(str(task.get("until_max_seconds", "0")).strip() or "0")
            if not math.isfinite(max_seconds) or max_seconds < 0:
                raise ValueError
        except (TypeError, ValueError):
            return f"第 {step_no} 步【直到条件成立】里的“最多等待秒数”必须是大于等于 0 的数字！"

        for condition in conditions:
            condition_no = condition.get("index")
            mode = condition.get("mode")
            image = str(condition.get("image", "")).strip()
            region_text = str(condition.get("region", "")).strip()
            if mode in ("图片出现", "图片消失", "区域变成指定图片"):
                if not image or not os.path.isfile(image):
                    return f"第 {step_no} 步【直到条件成立】的条件{condition_no}图片路径不存在！\n填入内容: {image}"
            if region_text and not parse_region_text(region_text):
                return f"第 {step_no} 步【直到条件成立】的条件{condition_no}区域格式错误，应为 x,y,w,h！\n填入内容: {region_text}"
            if mode in ("区域发生变化", "区域变成指定图片") and not parse_region_text(region_text):
                return f"第 {step_no} 步【直到条件成立】的条件{condition_no}必须填写或框选区域，格式为 x,y,w,h。"
            for key, label, minimum, maximum in (
                ("conf", "图片相似度", 0.05, 1.0),
                ("diff", "变化阈值", 0.0, 100.0),
                ("similarity", "区域相似度", 0.0, 100.0),
            ):
                try:
                    value = float(condition.get(key, "0"))
                    if not math.isfinite(value) or not minimum <= value <= maximum:
                        raise ValueError
                except (TypeError, ValueError):
                    return f"第 {step_no} 步【直到条件成立】的条件{condition_no}{label}必须在 {minimum:g} 到 {maximum:g} 之间！"
            if mode in ("图片出现", "图片消失"):
                valid, reason = template_detail_status(image, global_use_gray)
                if not valid:
                    return f"第 {step_no} 步【直到条件成立】的条件{condition_no}模板不安全：{reason}"
                budget_error = self._add_template_budget(
                    image, global_use_gray, global_scale_values, step_no
                )
                if budget_error:
                    return budget_error
            elif mode == "区域变成指定图片":
                budget_error = self._add_template_budget(image, False, (), step_no)
                if budget_error:
                    return budget_error
        return None


def validate_task_list(tasks: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> str | None:
    if not isinstance(config, Mapping):
        return "运行配置不是有效的配置对象。"
    if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes, bytearray)):
        return "步骤列表格式错误。"
    try:
        return TaskListValidator(config).validate(tasks)
    except (TypeError, ValueError, OverflowError) as error:
        return f"步骤配置格式错误：{error}"
