"""Mouse, keyboard, drag, screenshot and single-step action execution."""

import ctypes
import os
import time
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
from .expressions import ExpressionError
from .pyautogui_runtime import pyautogui
from .scale_memory import format_scale
from .text_input import send_unicode_text
from .window_actions import (
    activate_window,
    close_window,
    launch_application,
    wait_for_window,
)
from .log_policy import (
    LOG_ACTION,
    LOG_COORDINATES,
    LOG_CRITICAL,
    LOG_FLOW,
    LOG_PARAMETERS,
    LOG_RECOGNITION,
    LOG_STEP,
    LOG_TIMING,
)


@dataclass(frozen=True)
class StepActionContext:
    command: float
    value: object
    retry: int
    step_info: dict
    cache_key: str
    confidence: float
    use_gray: bool
    point_limit_enabled: bool = False
    point_limit_count: int = 0
    coordinate_step: dict | None = None
    image_click: dict | None = None
    task: dict | None = None
    coordinate_sequence: dict | None = None
    search_regions: list | None = None


ACTION_HANDLERS = {}


def action_handler(*command_codes):
    def register(function):
        for code in command_codes:
            normalized = float(code)
            if normalized in ACTION_HANDLERS:
                raise RuntimeError(f"Duplicate action handler for command {normalized}")
            ACTION_HANDLERS[normalized] = function
        return function

    return register


def registered_action_codes():
    return frozenset(ACTION_HANDLERS)

class ActionExecutionMixin:
    def _press_mouse_button(self, button, click_times=1):
        for _ in range(max(1, int(click_times))):
            pressed = False
            try:
                pyautogui.mouseDown(button=button)
                pressed = True
                time.sleep(self.click_hold)
            finally:
                if pressed:
                    pyautogui.mouseUp(button=button)
            if click_times > 1:
                time.sleep(0.02)

    def perform_mouse_click(self, x, y, clickTimes, lOrR, indicator_text=""):
        started_ns = time.perf_counter_ns()
        try:
            return self._perform_mouse_click_impl(
                x, y, clickTimes, lOrR, indicator_text
            )
        finally:
            self.performance.observe_since("action.mouse_click", started_ns)
            self.performance.increment("action.mouse_clicks", clickTimes)

    def _perform_mouse_click_impl(self, x, y, clickTimes, lOrR, indicator_text=""):
        pyautogui.moveTo(x, y, duration=self.move_duration)
        self._press_mouse_button(lOrR, clickTimes)

        self.report_click_indicator(x, y, indicator_text or f"{'左键' if lOrR == 'left' else '右键'}点击")

        if self.enable_dodge:
            final_x, final_y = self.dodge_x1, self.dodge_y1
            pyautogui.moveTo(final_x, final_y, duration=0)
            if self.enable_double_dodge:
                time.sleep(self.double_dodge_wait)
                final_x, final_y = self.dodge_x2, self.dodge_y2
                pyautogui.moveTo(final_x, final_y, duration=0)
            dodge_button = {
                "left": "left",
                "right": "right",
            }.get(str(getattr(self, "dodge_click_action", "none")))
            if dodge_button:
                self._press_mouse_button(dodge_button)
                self.performance.increment("action.dodge_clicks")
                label = "避让后左键单击" if dodge_button == "left" else "避让后右键单击"
                self.report_click_indicator(final_x, final_y, label)

    def mouseClick(self, clickTimes, lOrR, img_path, reTry, step_info=None, cache_key=None, task_conf=0.8, use_gray=True, point_limit_en=False, point_limit_count=0, coord_step_config=None, image_click_config=None, coord_sequence_config=None, search_regions=None):
        if step_info is None: step_info = {'step': 0, 'loop': 0, 'cmd': ''}
        start_time = time.monotonic()
        
        waiting_logged = False
        coord = self.parse_coordinate(img_path)
        use_all_targets = (not coord and self.multi_target_mode == "全部匹配")
        try:
            point_limit_count = max(0, int(float(point_limit_count)))
        except Exception:
            point_limit_count = 0
        point_limit_en = bool(point_limit_en) and not coord and point_limit_count > 0
        need_all_matches = not coord and (use_all_targets or point_limit_en)

        while True:
            if self.check_stop_flag(): return "stopped"
            if self.timeout_val > 0 and (time.monotonic() - start_time > self.timeout_val): 
                if self.log_level >= 1:
                    self.log(f"<font color='orange'>    [超时] 循环#{step_info['loop']} 步{step_info['step']}: 等待目标超时</font>", LOG_STEP)
                return "timeout"

            if coord:
                if coord_sequence_config:
                    seq_point, seq_state, seq_status = self._coord_sequence_location(step_info, coord_sequence_config)
                    if seq_status == "done":
                        if self.log_level >= 1:
                            self.log("<font color='gray'>    -> 自定义点位序列已点完，本步骤按设置跳过。</font>", LOG_COORDINATES)
                        return "skipped"
                    if not seq_point:
                        if self.log_level >= 1:
                            self.log("<font color='orange'>    -> 自定义点位序列为空，已跳过本步骤。</font>", LOG_COORDINATES)
                        return "skipped"
                    coord_state = None
                    locations = [(seq_point[0], seq_point[1], 1.0, 1.0)]
                elif coord_step_config:
                    _step_key, coord_state = self._get_coord_step_state(step_info, coord[0], coord[1])
                    locations = [(coord_state["x"], coord_state["y"], 1.0, 1.0)]
                else:
                    coord_state = None
                    locations = [(coord[0], coord[1], 1.0, 1.0)]
                find_time = 0.0
            elif need_all_matches:
                find_start = time.monotonic()
                locations = self.find_all_targets_optimized(img_path, cache_key, task_conf, use_gray, search_regions)
                find_time = time.monotonic() - find_start
            else:
                find_start = time.monotonic()
                location_tuple = self.find_target_optimized(img_path, cache_key, task_conf, use_gray, search_regions)
                find_time = time.monotonic() - find_start
                locations = [(
                    location_tuple[0],
                    location_tuple[1],
                    location_tuple[2],
                    location_tuple[3] if len(location_tuple) > 3 else task_conf,
                )] if location_tuple else []

            if locations:
                if not coord:
                    self.reset_recognition_miss(img_path, step_info)
                if search_regions and not coord:
                    before_count = len(locations)
                    locations = [
                        loc for loc in locations
                        if self.point_in_search_regions(*self.adjusted_image_click_point(img_path, loc, image_click_config), search_regions)
                    ]
                    if not locations:
                        self.record_recognition_miss(img_path, step_info)
                        if self.log_level >= 1:
                            self.log(f"<font color='orange'>    [跳过] 循环#{step_info['loop']} 步{step_info['step']}: 命中目标的实际点击点不在本步识别区域内，已过滤 {before_count} 个点位</font>", LOG_RECOGNITION)
                        return "not_found"
                if point_limit_en:
                    locations = self._filter_point_limit_targets(locations, img_path, step_info, point_limit_en, point_limit_count)
                    if not locations:
                        if not coord:
                            self.record_recognition_miss(img_path, step_info)
                        if self.log_level >= 1:
                            self.log(f"<font color='orange'>    [跳过] 循环#{step_info['loop']} 步{step_info['step']}: 当前图片所有识别点位都已达到同点点击上限</font>", LOG_RECOGNITION)
                        return "not_found"

                click_locations = locations if use_all_targets else locations[:1]

                try:
                    if self.verbose_log_enabled(LOG_TIMING):
                        self.log(
                            "    <font color='gray'>"
                            f"底层找图耗时 {find_time:.3f}s</font>",
                            LOG_TIMING,
                        )

                    if use_all_targets:
                        if self.log_level >= 1:
                            self.log(f"    -> 共识别到 {len(click_locations)} 个可点击目标，按【{self.multi_target_order}】顺序执行点击", LOG_RECOGNITION)
                    elif self.log_level >= 1:
                        x, y, scale, _score = click_locations[0]
                        click_x, click_y = self.adjusted_image_click_point(img_path, click_locations[0], image_click_config)
                        if image_click_config:
                            self.log(
                                f"    -> 已在坐标 ({int(x)}, {int(y)}) 锁定目标，"
                                f"缩放 {format_scale(scale)}x，实际点击图片内位置 "
                                f"({int(click_x)}, {int(click_y)})",
                                LOG_RECOGNITION,
                            )
                        else:
                            self.log(
                                f"    -> 已在坐标 ({int(x)}, {int(y)}) 锁定目标并执行点击，"
                                f"缩放 {format_scale(scale)}x",
                                LOG_RECOGNITION,
                            )

                    for target_idx, location_tuple in enumerate(click_locations, 1):
                        if self.check_stop_flag(): return "stopped"
                        x, y, scale, score = location_tuple
                        click_x, click_y = self.adjusted_image_click_point(img_path, location_tuple, image_click_config)
                        if use_all_targets and self.log_level >= 2:
                            if image_click_config:
                                self.log(f"       多目标 {target_idx}/{len(click_locations)} -> 命中中心({int(x)}, {int(y)})，点击({int(click_x)}, {int(click_y)})，相似度 {score:.3f} 缩放 {format_scale(scale)}x", LOG_RECOGNITION)
                            else:
                                self.log(f"       多目标 {target_idx}/{len(click_locations)} -> ({int(x)}, {int(y)}) 相似度 {score:.3f} 缩放 {format_scale(scale)}x", LOG_RECOGNITION)
                        if coord_step_config and coord_state and self.log_level >= 2:
                            self.log(self.coord_step_log_message(x, y, coord_state, coord_step_config), LOG_COORDINATES)
                        click_label = ("左键" if lOrR == "left" else "右键") + ("双击" if clickTimes == 2 else "单击")
                        self.perform_mouse_click(click_x, click_y, clickTimes, lOrR, click_label)
                        if coord_step_config and coord_state:
                            step_result = self._advance_coord_step_state(coord_state, coord_step_config, step_info)
                            if step_result == "locked_stop":
                                if self.log_level >= 0:
                                    self.log("<font color='red'><b>    -> 坐标步进达到移动上限，已按设置停止脚本。</b></font>", LOG_FLOW)
                                self.stop()
                                return "stopped"
                        if coord_sequence_config and coord:
                            self._advance_coord_sequence(seq_state)
                        if point_limit_en:
                            used_count = self._record_point_click(img_path, step_info, x, y)
                            if self.log_level >= 2:
                                self.log(f"       同点位已点击 {used_count}/{point_limit_count} 次", LOG_RECOGNITION)
                            
                except Exception as e: 
                    if self.log_enabled(LOG_CRITICAL, critical=True): self.log(f"<font color='red'>    [错误] 循环#{step_info['loop']} 步{step_info['step']}: {e}</font>", LOG_CRITICAL, critical=True)
                    return "error"
                return "success"
            else:
                if not coord:
                    self.record_recognition_miss(img_path, step_info)
                if reTry != -1:
                    if self.log_level >= 1:
                        self.log(f"<font color='orange'>    [未找到] 循环#{step_info['loop']} 步{step_info['step']}: 未能识别到目标图片 ({os.path.basename(img_path)})</font>", LOG_RECOGNITION)
                    return "not_found"
                else:
                    if not waiting_logged and self.log_level >= 1:
                        self.log("    -> 未发现目标，进入持续监听等待状态...", LOG_RECOGNITION)
                        waiting_logged = True
                    extra_delay = self.adaptive_extra_delay(img_path, step_info)
                    wake_context = None
                    if extra_delay > 0.0:
                        wake_context = self.recognition_wake_context(
                            img_path,
                            cache_key,
                            task_conf,
                            use_gray,
                            search_regions,
                            allow_fast_probe=not need_all_matches,
                        )
                    if not self.wait_recognition_interval(extra_delay, wake_context):
                        return "stopped"
                    continue

    def mouseDrag(self, button, val, step_info, recorded_duration=0.0):
        try:
            parts = val.split('->')
            p1 = parts[0].split(',')
            p2 = parts[1].split(',')
            x1, y1 = int(p1[0].strip()), int(p1[1].strip())
            x2, y2 = int(p2[0].strip()), int(p2[1].strip())
        except Exception:
            if self.log_enabled(LOG_CRITICAL, critical=True): self.log(f"<font color='red'>    [错误] 循环#{step_info['loop']} 步{step_info['step']}: 拖拽坐标格式错误，应为 x1,y1 -> x2,y2</font>", LOG_CRITICAL, critical=True)
            return "error"
        
        if self.log_level >= 1:
            self.log(f"    -> 正在从 ({x1},{y1}) 拖拽到 ({x2},{y2})", LOG_COORDINATES)
            
        pyautogui.moveTo(x1, y1, duration=self.move_duration)
        pressed = False
        try:
            pyautogui.mouseDown(button=button)
            pressed = True
            time.sleep(self.click_hold)
            try:
                replay_duration = max(0.0, float(recorded_duration or 0.0))
            except (TypeError, ValueError):
                replay_duration = 0.0
            replay_duration /= max(float(self.playback_speed or 1.0), 0.1)
            pyautogui.moveTo(
                x2,
                y2,
                duration=max(replay_duration, self.move_duration, 0.3),
            )
        finally:
            if pressed:
                pyautogui.mouseUp(button=button)
        self.report_click_indicator(x2, y2, "拖拽结束")
        return "success"

    def execute_task_once(self, cmd, val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en=False, point_limit_count=0, coord_step_config=None, image_click_config=None, task=None, coord_sequence_config=None, search_regions=None):
        started_ns = time.perf_counter_ns()
        try:
            return self._execute_task_once_impl(
                cmd,
                val,
                retry,
                step_info,
                cache_key,
                task_conf,
                use_gray,
                point_limit_en,
                point_limit_count,
                coord_step_config,
                image_click_config,
                task,
                coord_sequence_config,
                search_regions,
            )
        finally:
            try:
                command_key = f"{float(cmd):g}"
            except (TypeError, ValueError):
                command_key = "invalid"
            self.performance.observe_since("action.total", started_ns)
            self.performance.observe_since(f"action.command.{command_key}", started_ns)
            self.performance.increment("action.calls")

    def _execute_task_once_impl(self, cmd, val, retry, step_info, cache_key, task_conf, use_gray, point_limit_en=False, point_limit_count=0, coord_step_config=None, image_click_config=None, task=None, coord_sequence_config=None, search_regions=None):
        try:
            command = float(cmd)
        except (TypeError, ValueError):
            command = -1.0
        context = StepActionContext(
            command=command,
            value=val,
            retry=retry,
            step_info=step_info,
            cache_key=cache_key,
            confidence=task_conf,
            use_gray=use_gray,
            point_limit_enabled=point_limit_en,
            point_limit_count=point_limit_count,
            coordinate_step=coord_step_config,
            image_click=image_click_config,
            task=task,
            coordinate_sequence=coord_sequence_config,
            search_regions=search_regions,
        )
        handler = ACTION_HANDLERS.get(command)
        if handler is None:
            if self.log_enabled(LOG_CRITICAL, critical=True):
                self.log(
                    f"<font color='red'>    [严重异常] 循环#{step_info['loop']} 步"
                    f"{step_info['step']}: 未注册的指令类型 {cmd}</font>",
                    LOG_CRITICAL,
                    critical=True,
                )
            return "error"
        try:
            return handler(self, context)
        except Exception as error:
            if self.log_enabled(LOG_CRITICAL, critical=True):
                self.log(
                    f"<font color='red'>    [严重异常] 循环#{step_info['loop']} 步"
                    f"{step_info['step']}: 执行崩溃 -> {error}</font>",
                    LOG_CRITICAL,
                    critical=True,
                )
            return "error"

    def _click_from_context(self, context, times, button):
        return self.mouseClick(
            times,
            button,
            context.value,
            context.retry,
            context.step_info,
            context.cache_key,
            context.confidence,
            context.use_gray,
            context.point_limit_enabled,
            context.point_limit_count,
            context.coordinate_step,
            context.image_click,
            context.coordinate_sequence,
            context.search_regions,
        )

    @action_handler(1.0)
    def _execute_left_click(self, context):
        return self._click_from_context(context, 1, "left")

    @action_handler(2.0)
    def _execute_left_double_click(self, context):
        return self._click_from_context(context, 2, "left")

    @action_handler(3.0)
    def _execute_right_click(self, context):
        return self._click_from_context(context, 1, "right")

    @action_handler(TASK_TYPE_UNTIL)
    def _execute_until_condition(self, context):
        return self.execute_until_conditions(
            context.task or {}, context.step_info, context.use_gray
        )

    @action_handler(TASK_TYPE_SET_VARIABLE)
    def _execute_set_variable(self, context):
        try:
            name, value = self.set_runtime_variable(
                context.value, context.step_info
            )
        except ExpressionError as error:
            if self.log_level >= 0:
                self.log(
                    f"<font color='red'>    [变量错误] 第 {context.step_info['step']} 步：{error}</font>",
                    LOG_CRITICAL,
                    critical=True,
                )
            return "error"
        if self.log_level >= 1:
            self.log(f"    -> 运行变量 {name} 已更新", LOG_ACTION)
        if self.log_level >= 2:
            self.log(f"    <font color='gray'>变量结果：{name} = {value!r}</font>", LOG_PARAMETERS)
        return "success"

    @action_handler(TASK_TYPE_EXPRESSION)
    def _execute_expression_condition(self, context):
        try:
            result = self.evaluate_runtime_expression(
                context.value, context.step_info
            )
        except ExpressionError as error:
            if self.log_level >= 0:
                self.log(
                    f"<font color='red'>    [表达式错误] 第 {context.step_info['step']} 步：{error}</font>",
                    LOG_CRITICAL,
                    critical=True,
                )
            return "error"
        matched = bool(result)
        if self.log_level >= 1:
            self.log(
                "    -> 表达式判断结果：" + ("满足" if matched else "不满足"),
                LOG_FLOW,
            )
        return "condition_true" if matched else "condition_false"

    @action_handler(TASK_TYPE_LAUNCH_APP)
    def _execute_launch_application(self, context):
        pid = launch_application(context.value)
        if self.log_level >= 1:
            self.log(f"    -> 程序已启动，进程 ID：{pid}", LOG_ACTION)
        return "success"

    @action_handler(TASK_TYPE_WAIT_WINDOW)
    def _execute_wait_for_window(self, context):
        configured = (context.task or {}).get("window_timeout", 0)
        timeout = self.parse_float_value(configured, 0.0)
        if timeout <= 0:
            timeout = self.timeout_val if self.timeout_val > 0 else 10.0
        hwnd = wait_for_window(context.value, timeout, self.check_stop_flag)
        if self.check_stop_flag():
            return "stopped"
        if not hwnd:
            if self.log_level >= 1:
                self.log(
                    f"<font color='orange'>    [超时] 未等到窗口：{context.value}</font>",
                    LOG_ACTION,
                )
            return "timeout"
        if self.log_level >= 1:
            self.log(f"    -> 已检测到窗口：{context.value}", LOG_ACTION)
        return "success"

    @action_handler(TASK_TYPE_ACTIVATE_WINDOW)
    def _execute_activate_window(self, context):
        success = activate_window(context.value)
        if self.log_level >= 1:
            self.log(
                f"    -> {'已激活' if success else '未找到或无法激活'}窗口：{context.value}",
                LOG_ACTION,
            )
        return "success" if success else "not_found"

    @action_handler(TASK_TYPE_CLOSE_WINDOW)
    def _execute_close_window(self, context):
        success = close_window(context.value)
        if self.log_level >= 1:
            self.log(
                f"    -> {'已请求关闭' if success else '未找到'}窗口：{context.value}",
                LOG_ACTION,
            )
        return "success" if success else "not_found"

    def _execute_uia_action(self, context, operation, value=""):
        binding = (context.task or {}).get("uia_binding")
        result = self.task_window_backend().uia_control_action(
            binding, operation, value
        )
        if result.get("success"):
            if self.log_level >= 1:
                method = result.get("method") or "UI Automation"
                self.log(f"    -> 控件操作成功（{method}）", LOG_ACTION)
            return result
        if self.log_level >= 1:
            error = result.get("error") or "目标控件不支持此操作"
            self.log(
                f"<font color='orange'>    [控件操作失败] {error}</font>",
                LOG_ACTION,
            )
        return result

    @action_handler(TASK_TYPE_UIA_CLICK)
    def _execute_uia_click(self, context):
        result = self._execute_uia_action(context, "activate")
        return "success" if isinstance(result, dict) and result.get("success") else "not_found"

    @action_handler(TASK_TYPE_UIA_SET_VALUE)
    def _execute_uia_set_value(self, context):
        result = self._execute_uia_action(context, "set_value", context.value)
        return "success" if isinstance(result, dict) and result.get("success") else "not_found"

    @action_handler(TASK_TYPE_UIA_READ_VALUE)
    def _execute_uia_read_value(self, context):
        result = self._execute_uia_action(context, "read_value")
        if not isinstance(result, dict) or not result.get("success"):
            return "not_found"
        try:
            name, _value = self.store_runtime_variable(
                context.value, str(result.get("value", ""))[:4096]
            )
        except ExpressionError as error:
            self.log(
                f"<font color='red'>    [变量错误] {error}</font>",
                LOG_CRITICAL,
                critical=True,
            )
            return "error"
        if self.log_level >= 1:
            self.log(f"    -> 控件文本已保存到变量 {name}", LOG_ACTION)
        return "success"

    def _send_private_text(self, value, label):
        text = str(value)
        if self.log_level >= 1:
            self.log(f"    -> {label}（{len(text)} 个字符）", LOG_ACTION)
        send_unicode_text(text)
        return "success"

    @action_handler(TASK_TYPE_SECRET_TEXT)
    def _execute_secret_text(self, context):
        try:
            secret = self.credential_store().get(context.value)
        except Exception as error:
            if self.log_level >= 0:
                self.log(
                    f"<font color='red'>    [凭据错误] {error}</font>",
                    LOG_CRITICAL,
                    critical=True,
                )
            return "error"
        return self._send_private_text(secret, "正在输入秘密文本")

    @action_handler(10.0)
    def _execute_left_drag(self, context):
        return self.mouseDrag(
            "left",
            context.value,
            context.step_info,
            (context.task or {}).get("recorded_duration", 0.0),
        )

    @action_handler(11.0)
    def _execute_right_drag(self, context):
        return self.mouseDrag(
            "right",
            context.value,
            context.step_info,
            (context.task or {}).get("recorded_duration", 0.0),
        )

    @action_handler(12.0)
    def _execute_message(self, context):
        if self.log_level >= 1:
            self.log(f"    -> 触发弹窗提醒: {context.value}", LOG_ACTION)
        ctypes.windll.user32.MessageBoxW(
            0,
            str(context.value),
            "脚本提醒",
            0x00040000 | 0x00010000 | 0x00000040,
        )
        return "success"

    @action_handler(13.0)
    def _execute_stop(self, context):
        if self.log_level >= 1:
            self.log(f"    -> 触发停止指令，脚本即将终止。备注: {context.value}", LOG_ACTION)
        self.stop()
        return "success"

    @action_handler(14.0)
    def _execute_sound(self, context):
        if self.log_level >= 0:
            self.log(f"<br><font color='#00BCD4' size='4'><b>声音提示: {context.value}</b></font><br>", LOG_ACTION)
        try:
            import winsound

            winsound.MessageBeep(0x00000040)
        except Exception:
            pass
        return "success"

    @action_handler(8.0)
    def _execute_hover(self, context):
        coordinate = self.parse_coordinate(context.value)
        if coordinate:
            location = (coordinate[0], coordinate[1], 1.0)
            find_time = 0.0
        else:
            find_start = time.monotonic()
            location = self.find_target_optimized(
                context.value,
                context.cache_key,
                context.confidence,
                context.use_gray,
                context.search_regions,
            )
            find_time = time.monotonic() - find_start
        if not location:
            if self.log_level >= 1:
                self.log(
                    f"<font color='orange'>    [异常] 循环#{context.step_info['loop']} 步"
                    f"{context.step_info['step']}: 悬停失败，未识别到目标</font>",
                    LOG_RECOGNITION,
                )
            return "not_found"
        x, y, scale = location[0], location[1], location[2]
        if self.verbose_log_enabled(LOG_TIMING):
            self.log(
                "    <font color='gray'>=> 底层找图耗时 "
                f"{find_time:.3f}s，缩放: {format_scale(scale)}x</font>",
                LOG_TIMING,
            )
        if self.log_level >= 1:
            self.log(f"    -> 已悬停在坐标 ({int(x)}, {int(y)})", LOG_COORDINATES)
        pyautogui.moveTo(x, y, duration=self.move_duration)
        self.report_click_indicator(x, y, "悬停")
        return "success"

    @action_handler(4.0)
    def _execute_text(self, context):
        return self._send_private_text(context.value, "正在输入文本")

    @action_handler(5.0)
    def _execute_wait(self, context):
        wait_time = float(context.value) / max(self.playback_speed, 0.1)
        if self.log_level >= 1:
            self.log(
                f"    -> 强制静默等待 {wait_time:.2f} 秒 (原录制设定 {context.value}s, "
                f"倍速 {self.playback_speed}x)...",
                LOG_ACTION,
            )
        end_time = time.monotonic() + wait_time
        while time.monotonic() < end_time:
            if self.check_stop_flag():
                return "stopped"
            time.sleep(min(0.05, max(0.0, end_time - time.monotonic())))
        return "success"

    @action_handler(6.0)
    def _execute_scroll(self, context):
        if self.log_level >= 1:
            self.log(f"    -> 鼠标滚轮滑动 {context.value}", LOG_ACTION)
        pyautogui.scroll(int(float(context.value)))
        return "success"

    @action_handler(7.0)
    def _execute_hotkey(self, context):
        if self.log_level >= 1:
            self.log(f"    -> 触发系统按键组合: {context.value}", LOG_ACTION)
        pyautogui.hotkey(*[key.strip() for key in str(context.value).lower().split("+")])
        return "success"

    @action_handler(9.0)
    def _execute_screenshot(self, context):
        path = str(context.value or "").strip()
        if not path:
            raise ValueError("截图保存路径不能为空")
        if os.path.isdir(path):
            milliseconds = int(time.time_ns() // 1_000_000) % 1000
            path = os.path.join(
                path, f"ss_{time.strftime('%Y%m%d_%H%M%S')}_{milliseconds:03d}.png"
            )
        parent_dir = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(parent_dir):
            raise FileNotFoundError(f"截图保存目录不存在：{parent_dir}")
        regions = self.normalized_regions(getattr(self, "scan_regions", []))
        region = self.region_bounding_rect(regions) if regions else self.scan_region
        screenshot, _offset_x, _offset_y = self.capture_screenshot(region)
        screenshot.save(path)
        if self.log_level >= 1:
            self.log(f"    -> 已截图并保存至 {path}", LOG_ACTION)
        return "success"
