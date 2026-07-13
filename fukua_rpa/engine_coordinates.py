"""Runtime state for coordinate sequences and generated click paths."""

from .task_model import (
    coord_step_delta_values,
    parse_coord_step_manual_points,
    parse_coordinate_sequence,
)
from .log_policy import LOG_COORDINATES, LOG_CRITICAL

class CoordinatePathMixin:
    def coord_step_options(self, task):
        if not task or not self.as_bool(task.get("coord_step_en", False)):
            return None
        try:
            every = max(1, int(float(task.get("coord_step_every", 1))))
        except Exception:
            every = 1
        return {
            "every": every,
            "direction": str(task.get("coord_step_direction", "向下")),
            "distance": self.parse_float_value(task.get("coord_step_distance", 0), 0.0),
            "dx": self.parse_float_value(task.get("coord_step_dx", 0), 0.0),
            "dy": self.parse_float_value(task.get("coord_step_dy", 0), 0.0),
            "point": str(task.get("coord_step_point", "")).strip(),
            "max_steps": max(0, int(self.parse_float_value(task.get("coord_step_max_steps", 0), 0.0))),
            "max_distance": max(0.0, self.parse_float_value(task.get("coord_step_max_distance", 0), 0.0)),
            "stop": self.as_bool(task.get("coord_step_stop", False)),
            "reset_after": max(0, int(self.parse_float_value(task.get("coord_step_reset_after", 0), 0.0))),
            "manual_points": parse_coord_step_manual_points(task.get("coord_step_manual_points", "{}"))
        }

    def coord_sequence_options(self, task):
        if not task or not self.as_bool(task.get("coord_sequence_en", False)):
            return None
        points = parse_coordinate_sequence(task.get("coord_sequence_points", ""))
        if not points:
            return None
        end_action = str(task.get("coord_sequence_end_action", "点完后跳过本步"))
        if end_action not in ["点完后跳过本步", "点完后停在最后一个", "点完后循环"]:
            end_action = "点完后跳过本步"
        return {"points": points, "end_action": end_action}

    def _coord_sequence_key(self, step_info):
        return int(step_info.get("step", 0)) if step_info else 0

    def _coord_sequence_location(self, step_info, options):
        points = list(options.get("points", []))
        if not points:
            return None, None, "empty"
        key = self._coord_sequence_key(step_info)
        state = self.coord_sequence_states.setdefault(key, {"index": 0})
        idx = int(state.get("index", 0))
        if idx >= len(points):
            action = options.get("end_action", "点完后跳过本步")
            if action == "点完后循环":
                idx = 0
                state["index"] = 0
            elif action == "点完后停在最后一个":
                idx = len(points) - 1
            else:
                return None, state, "done"
        return points[idx], state, "ok"

    def _advance_coord_sequence(self, state):
        if state is not None:
            state["index"] = int(state.get("index", 0)) + 1

    def _coord_step_key(self, step_info, base_x, base_y):
        return (int(step_info.get("step", 0)) if step_info else 0, int(base_x), int(base_y))

    def _coord_step_delta(self, options):
        direction = options.get("direction", "向下")
        distance = options.get("distance", 0.0)
        return coord_step_delta_values(direction, distance, options.get("dx", 0.0), options.get("dy", 0.0))

    def _get_coord_step_state(self, step_info, base_x, base_y):
        key = self._coord_step_key(step_info, base_x, base_y)
        if key not in self.coord_step_states:
            self.coord_step_states[key] = {
                "base_x": float(base_x), "base_y": float(base_y),
                "x": float(base_x), "y": float(base_y),
                "clicks_since_move": 0,
                "clicks_since_reset": 0,
                "offset_times": 0,
                "movement_locked": False
            }
        return key, self.coord_step_states[key]

    def _reset_coord_step_state(self, state):
        state["x"] = float(state.get("base_x", state.get("x", 0.0)))
        state["y"] = float(state.get("base_y", state.get("y", 0.0)))
        state["clicks_since_move"] = 0
        state["clicks_since_reset"] = 0
        state["offset_times"] = 0
        state["movement_locked"] = False

    def _advance_coord_step_state(self, state, options, step_info):
        reset_after = max(0, int(options.get("reset_after", 0)))
        state["clicks_since_reset"] = state.get("clicks_since_reset", 0) + 1
        if reset_after > 0 and state["clicks_since_reset"] >= reset_after:
            self._reset_coord_step_state(state)
            if self.log_level >= 2:
                self.log(f"       坐标步进已成功点击 {reset_after} 次，已重置到起点（{int(state['x'])}，{int(state['y'])}）", LOG_COORDINATES)
            return "reset"

        if state.get("movement_locked"):
            return "locked_stop" if options.get("stop") else "locked"

        state["clicks_since_move"] += 1
        if state["clicks_since_move"] < options["every"]:
            return "ok"

        state["clicks_since_move"] = 0
        if options["direction"] == "移动到新点位":
            point = self.parse_coordinate(options.get("point", ""))
            if not point:
                if self.log_enabled(LOG_CRITICAL, critical=True):
                    self.log("<font color='red'>    -> 坐标步进的新点位格式错误，已停止本步进移动。</font>", LOG_CRITICAL, critical=True)
                state["movement_locked"] = True
                return "locked_stop" if options.get("stop") else "locked"

            total_points = options["max_steps"] if options["max_steps"] >= 2 else 2
            max_offset_times = total_points - 1
            if state["offset_times"] >= max_offset_times:
                state["movement_locked"] = True
                if self.log_level >= 1:
                    self.log(f"<font color='orange'>    -> 坐标步进已到达目标点位，本路径共 {total_points} 个点，后续不再移动。</font>", LOG_COORDINATES)
                return "locked_stop" if options.get("stop") else "locked"

            next_index = state["offset_times"] + 1
            ratio = next_index / max_offset_times
            next_x = state["base_x"] + (float(point[0]) - state["base_x"]) * ratio
            next_y = state["base_y"] + (float(point[1]) - state["base_y"]) * ratio
            manual_point = options.get("manual_points", {}).get(next_index)
            if manual_point:
                next_x, next_y = manual_point
        else:
            if options["max_steps"] > 0 and state["offset_times"] >= options["max_steps"]:
                state["movement_locked"] = True
                if self.log_level >= 1:
                    self.log(f"<font color='orange'>    -> 坐标步进已达到最大偏移次数 {options['max_steps']}，后续不再移动。</font>", LOG_COORDINATES)
                return "locked_stop" if options.get("stop") else "locked"

            dx, dy = self._coord_step_delta(options)
            next_x, next_y = state["x"] + dx, state["y"] + dy

        distance_from_base = ((next_x - state["base_x"]) ** 2 + (next_y - state["base_y"]) ** 2) ** 0.5
        if options["max_distance"] > 0 and distance_from_base > options["max_distance"]:
            state["movement_locked"] = True
            if self.log_level >= 1:
                self.log(f"<font color='orange'>    -> 坐标步进将超过最大偏移距离 {options['max_distance']:.1f}px，后续不再移动。</font>", LOG_COORDINATES)
            return "locked_stop" if options.get("stop") else "locked"

        state["x"], state["y"] = next_x, next_y
        state["offset_times"] += 1
        return "moved"

    def coord_step_log_message(self, x, y, state, options):
        next_after = options["every"] - state["clicks_since_move"]
        if next_after <= 0:
            next_after = options["every"]
        reset_after = max(0, int(options.get("reset_after", 0)))
        reset_text = ""
        if reset_after > 0:
            reset_count = min(state.get("clicks_since_reset", 0) + 1, reset_after)
            reset_text = f"，重置计数 {reset_count}/{reset_after}"

        if options.get("direction") == "移动到新点位":
            total_points = options["max_steps"] if options["max_steps"] >= 2 else 2
            point_no = min(state["offset_times"] + 1, total_points)
            manual_text = "，手动修正点" if state["offset_times"] in options.get("manual_points", {}) else ""
            return f"       当前点击位置（{int(x)}，{int(y)}），为第{state['offset_times']}次偏移（第{point_no}/{total_points}个点位{manual_text}），将在第{next_after}次后进行下次偏移{reset_text}"

        return f"       当前点击位置（{int(x)}，{int(y)}），为第{state['offset_times']}次偏移，将在第{next_after}次后进行下次偏移{reset_text}"
