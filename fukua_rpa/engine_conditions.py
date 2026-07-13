"""Image and region conditions used by the 'until condition' task."""

import os
import time

from PIL import Image, ImageChops, ImageStat

from .task_model import format_region_text, parse_region_text, until_condition_list_from_data
from .log_policy import LOG_CRITICAL, LOG_RECOGNITION

class UntilConditionMixin:
    def condition_screenshot(self, region):
        key = tuple(int(value) for value in region)
        cache = getattr(self, "_until_capture_cache", None)
        if cache is not None and key in cache:
            self.performance.increment("condition.screenshot_cache_hits")
            return cache[key]
        captured = self.capture_screenshot(region)
        if cache is not None:
            cache[key] = captured
            self.performance.increment("condition.screenshot_cache_misses")
        return captured

    def until_conditions_from_task(self, task):
        return until_condition_list_from_data(task or {})

    def until_task_state_key(self, step_info):
        step_no = int(step_info.get("step", 0)) if step_info else 0
        return step_no

    def condition_cache_key(self, image_path, cond_idx, task_conf, use_gray):
        return f"until_{cond_idx}_{image_path}_{self.min_scale}_{self.max_scale}_{self.scale_step}_{task_conf}_{use_gray}"

    def condition_region(self, cond):
        return parse_region_text(cond.get("region", ""))

    def condition_confidence(self, cond):
        return max(0.05, min(1.0, self.parse_float_value(cond.get("conf", 0.8), 0.8)))

    def condition_diff_threshold(self, cond):
        return max(0.0, min(100.0, self.parse_float_value(cond.get("diff", 8), 8.0)))

    def condition_similarity_threshold(self, cond):
        return max(0.0, min(100.0, self.parse_float_value(cond.get("similarity", 90), 90.0)))

    def resized_for_compare(self, image, target_size=None, max_side=260):
        img = image.convert("RGB")
        if target_size:
            return img.resize(target_size)
        w, h = img.size
        longest = max(w, h)
        if longest > max_side:
            scale = max_side / float(longest)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        return img

    def image_difference_percent(self, img_a, img_b):
        a = self.resized_for_compare(img_a)
        b = self.resized_for_compare(img_b, a.size)
        diff = ImageChops.difference(a, b)
        stat = ImageStat.Stat(diff)
        mean = sum(stat.mean[:3]) / 3.0
        return mean / 255.0 * 100.0

    def image_similarity_percent(self, current_img, template_img):
        template = self.resized_for_compare(template_img)
        current = self.resized_for_compare(current_img, template.size)
        diff = ImageChops.difference(current, template)
        stat = ImageStat.Stat(diff)
        mean = sum(stat.mean[:3]) / 3.0
        return max(0.0, 100.0 - (mean / 255.0 * 100.0))

    def find_condition_image(self, cond, step_info, use_gray):
        image_path = str(cond.get("image", "")).strip()
        if not image_path or not os.path.exists(image_path):
            return False, "图片不存在"
        conf = self.condition_confidence(cond)
        cache_key = self.condition_cache_key(image_path, cond.get("index", 0), conf, use_gray)
        self.scale_options_cache[str(cache_key)] = (self.min_scale, self.max_scale, self.scale_step)
        region = self.condition_region(cond)

        if region:
            try:
                screenshot_pil, offset_x, offset_y = self.condition_screenshot(region)
                found = self.find_target_in_screenshot(image_path, cache_key, conf, use_gray, screenshot_pil, offset_x, offset_y)
            except Exception as e:
                return False, f"区域识别异常: {e}"
        else:
            found = self.find_target_optimized(image_path, cache_key, conf, use_gray)

        if found:
            x, y = found[0], found[1]
            return True, f"找到图片 {os.path.basename(image_path)} ({int(x)}, {int(y)})"
        return False, f"未找到图片 {os.path.basename(image_path)}"

    def evaluate_region_changed_condition(self, cond, step_info):
        region = self.condition_region(cond)
        if not region:
            return False, "未设置区域"
        try:
            screenshot_pil, _offset_x, _offset_y = self.condition_screenshot(region)
        except Exception as e:
            return False, f"截图异常: {e}"

        key = (self.until_task_state_key(step_info), int(cond.get("index", 0)), "changed", format_region_text(region))
        baseline = self.until_condition_baselines.get(key)
        if baseline is None:
            self.until_condition_baselines[key] = screenshot_pil.copy()
            return False, "已记录区域基准，等待变化"

        compare_started_ns = time.perf_counter_ns()
        diff = self.image_difference_percent(baseline, screenshot_pil)
        self.performance.observe_since("condition.image_compare", compare_started_ns)
        threshold = self.condition_diff_threshold(cond)
        return diff >= threshold, f"区域变化 {diff:.1f}% / 阈值 {threshold:.1f}%"

    def evaluate_region_matches_image_condition(self, cond, step_info):
        region = self.condition_region(cond)
        if not region:
            return False, "未设置区域"
        image_path = str(cond.get("image", "")).strip()
        if not image_path or not os.path.exists(image_path):
            return False, "图片不存在"
        try:
            screenshot_pil, _offset_x, _offset_y = self.condition_screenshot(region)
            if image_path not in self.img_cache:
                img = Image.open(image_path)
                img.load()
                self.img_cache[image_path] = img
            template = self.img_cache[image_path]
            compare_started_ns = time.perf_counter_ns()
            similarity = self.image_similarity_percent(screenshot_pil, template)
            self.performance.observe_since("condition.image_compare", compare_started_ns)
        except Exception as e:
            return False, f"区域对比异常: {e}"

        threshold = self.condition_similarity_threshold(cond)
        return similarity >= threshold, f"区域相似 {similarity:.1f}% / 阈值 {threshold:.1f}%"

    def evaluate_until_condition(self, cond, step_info, use_gray):
        started_ns = time.perf_counter_ns()
        try:
            return self._evaluate_until_condition_impl(cond, step_info, use_gray)
        finally:
            self.performance.observe_since("condition.evaluate", started_ns)
            self.performance.increment("condition.evaluations")

    def _evaluate_until_condition_impl(self, cond, step_info, use_gray):
        mode = cond.get("mode", "图片出现")
        if mode == "图片出现":
            return self.find_condition_image(cond, step_info, use_gray)
        if mode == "图片消失":
            found, detail = self.find_condition_image(cond, step_info, use_gray)
            if "不存在" in detail or "异常" in detail:
                return False, detail
            return (not found), ("图片已消失" if found is False else detail)
        if mode == "区域发生变化":
            return self.evaluate_region_changed_condition(cond, step_info)
        if mode == "区域变成指定图片":
            return self.evaluate_region_matches_image_condition(cond, step_info)
        return False, "未知条件类型"

    def execute_until_conditions(self, task, step_info, use_gray):
        conditions = self.until_conditions_from_task(task)
        if not conditions:
            if self.log_enabled(LOG_CRITICAL, critical=True):
                self.log(
                    "<font color='red'>    [直到条件成立] 没有启用任何条件。</font>",
                    LOG_CRITICAL,
                    critical=True,
                )
            return "error"

        logic = str(task.get("until_logic", "全部满足"))
        results = []
        details = []
        previous_capture_cache = getattr(self, "_until_capture_cache", None)
        self._until_capture_cache = {}
        try:
            for cond in conditions:
                if self.check_stop_flag():
                    return "stopped"
                matched, detail = self.evaluate_until_condition(
                    cond, step_info, use_gray
                )
                results.append(bool(matched))
                details.append(f"条件{cond.get('index')}[{cond.get('mode')}]: {'满足' if matched else '未满足'}，{detail}")
                if logic == "任一满足" and matched:
                    break
                if logic != "任一满足" and not matched:
                    break
        finally:
            self._until_capture_cache = previous_capture_cache

        satisfied = any(results) if logic == "任一满足" else all(results)
        if self.log_level >= 1:
            color = "#4CAF50" if satisfied else "#FF9800"
            detail_text = "；".join(details)
            self.log(
                f"<font color='{color}'>    [直到条件成立] {'条件已满足' if satisfied else '条件未满足'}：{detail_text}</font>",
                LOG_RECOGNITION,
            )
        return "condition_true" if satisfied else "condition_false"

    def until_false_runtime(self, task, step_info):
        key = self.until_task_state_key(step_info)
        if key not in self.until_condition_started_at:
            self.until_condition_started_at[key] = time.monotonic()
        self.until_condition_counts[key] = self.until_condition_counts.get(key, 0) + 1
        false_count = self.until_condition_counts[key]
        elapsed = time.monotonic() - self.until_condition_started_at.get(key, time.monotonic())
        max_checks = self.non_negative_int_value(task.get("until_max_checks", 0), 0)
        max_seconds = max(0.0, self.parse_float_value(task.get("until_max_seconds", 0), 0.0))
        reached = False
        reason = ""
        if max_checks > 0 and false_count >= max_checks:
            reached = True
            reason = f"未满足检查已达到 {false_count}/{max_checks} 次"
        if max_seconds > 0 and elapsed >= max_seconds:
            reached = True
            reason = f"等待条件已达到 {elapsed:.1f}/{max_seconds:.1f} 秒"
        return reached, reason, false_count, elapsed

    def reset_until_runtime(self, step_info):
        key = self.until_task_state_key(step_info)
        self.until_condition_counts.pop(key, None)
        self.until_condition_started_at.pop(key, None)
        for baseline_key in list(self.until_condition_baselines.keys()):
            if baseline_key and baseline_key[0] == key:
                self.until_condition_baselines.pop(baseline_key, None)
