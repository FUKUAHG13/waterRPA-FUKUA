"""Pure task parsing and coordinate-path helpers shared by UI and engine."""

import json
import os

from .constants import UNTIL_CONDITION_MODES


def config_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "启用", "是")
    return bool(value)


def parse_coordinate_text(value):
    try:
        text = str(value).strip()
        if "," not in text:
            return None
        parts = text.split(",")
        if len(parts) != 2:
            return None
        return int(parts[0].strip()), int(parts[1].strip())
    except (TypeError, ValueError):
        return None


def parse_float_text(value, default=0.0):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_region_text(value):
    try:
        text = str(value or "").strip()
        if not text:
            return None
        parts = [part.strip() for part in text.replace("，", ",").split(",")]
        if len(parts) != 4:
            return None
        x, y, width, height = [int(float(part)) for part in parts]
        if width <= 0 or height <= 0:
            return None
        return x, y, width, height
    except (TypeError, ValueError):
        return None


def format_region_text(region):
    try:
        x, y, width, height = [int(float(value)) for value in region]
        return f"{x},{y},{width},{height}"
    except (TypeError, ValueError):
        return ""


def until_condition_defaults():
    data = {
        "until_logic": "全部满足",
        "until_false_jump": "1",
        "until_true_jump": "0",
        "until_max_checks": "0",
        "until_max_seconds": "0",
        "until_on_limit": "继续下一步",
    }
    for index in range(1, 4):
        data.update({
            f"until_cond{index}_en": index == 1,
            f"until_cond{index}_mode": "图片出现",
            f"until_cond{index}_image": "",
            f"until_cond{index}_region": "",
            f"until_cond{index}_conf": "0.8",
            f"until_cond{index}_diff": "8",
            f"until_cond{index}_similarity": "90",
        })
    return data


def until_condition_list_from_data(data):
    conditions = []
    for index in range(1, 4):
        if not config_bool(data.get(f"until_cond{index}_en", index == 1)):
            continue
        mode = str(data.get(f"until_cond{index}_mode", "图片出现"))
        if mode not in UNTIL_CONDITION_MODES:
            mode = "图片出现"
        conditions.append({
            "index": index,
            "mode": mode,
            "image": str(data.get(f"until_cond{index}_image", "")).strip(),
            "region": str(data.get(f"until_cond{index}_region", "")).strip(),
            "conf": str(data.get(f"until_cond{index}_conf", "0.8")).strip(),
            "diff": str(data.get(f"until_cond{index}_diff", "8")).strip(),
            "similarity": str(data.get(f"until_cond{index}_similarity", "90")).strip(),
        })
    return conditions


def until_condition_summary(data):
    conditions = until_condition_list_from_data(data)
    if not conditions:
        return "未设置条件"
    parts = []
    for condition in conditions[:3]:
        mode = condition["mode"]
        image = os.path.basename(condition.get("image", "")) if condition.get("image") else ""
        region = condition.get("region", "")
        if mode == "区域发生变化":
            description = f"区域变化 {region or '未选区域'}"
        elif mode == "区域变成指定图片":
            description = f"区域变成 {image or '未选图片'}"
        else:
            description = f"{mode} {image or '未选图片'}"
            if region:
                description += f"@{region}"
        parts.append(description)
    logic = str(data.get("until_logic", "全部满足"))
    false_jump = str(data.get("until_false_jump", "1")).strip() or "1"
    true_jump = str(data.get("until_true_jump", "0")).strip() or "0"
    true_text = "下一步" if true_jump == "0" else f"第{true_jump}步"
    if len(parts) == 1:
        return f"{parts[0]}；未满足→第{false_jump}步，满足→{true_text}"
    return f"{logic}：{'；'.join(parts)}；未满足→第{false_jump}步，满足→{true_text}"


def parse_coord_step_manual_points(value):
    try:
        raw = value if isinstance(value, dict) else json.loads(str(value or "").strip())
        points = {}
        for key, coordinate in raw.items():
            index = int(key)
            if index <= 0:
                continue
            if isinstance(coordinate, (list, tuple)) and len(coordinate) >= 2:
                points[index] = (float(coordinate[0]), float(coordinate[1]))
        return points
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def serialize_coord_step_manual_points(points):
    normalized = {}
    for index, coordinate in (points or {}).items():
        try:
            index = int(index)
            if index <= 0:
                continue
            x, y = coordinate
            normalized[str(index)] = [int(round(float(x))), int(round(float(y)))]
        except (TypeError, ValueError):
            continue
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def parse_coordinate_sequence(value):
    points = []
    text = str(value or "").strip()
    if not text:
        return points
    normalized = text.replace("\n", ";").replace("，", ",")
    for chunk in normalized.split(";"):
        coordinate = parse_coordinate_text(chunk.strip())
        if coordinate:
            points.append(coordinate)
    return points


def serialize_coordinate_sequence(points):
    result = []
    for point in points or []:
        try:
            x, y = point
            result.append(f"{int(float(x))},{int(float(y))}")
        except (TypeError, ValueError):
            continue
    return "; ".join(result)


# Mojibake direction names remain temporarily for compatibility with old saved profiles.
def coord_step_delta_values(direction, distance, dx, dy):
    direction = str(direction)
    if direction in ("\u5411\u4e0a", "鍚戜笂"):
        return 0.0, -distance
    if direction in ("\u5411\u4e0b", "鍚戜笅"):
        return 0.0, distance
    if direction in ("\u5411\u5de6", "鍚戝乏"):
        return -distance, 0.0
    if direction in ("\u5411\u53f3", "鍚戝彸"):
        return distance, 0.0
    if direction == "\u81ea\u5b9a\u4e49\u504f\u79fb" or direction.startswith("鑷"):
        return dx, dy
    return 0.0, 0.0


def build_coord_step_positions(base_x, base_y, options, max_points=200):
    base_x = float(base_x)
    base_y = float(base_y)
    direction = str(options.get("direction", "向下"))
    max_steps = max(0, int(parse_float_text(options.get("max_steps", 0), 0.0)))
    max_distance = max(0.0, parse_float_text(options.get("max_distance", 0), 0.0))
    positions = [(base_x, base_y)]

    if direction == "\u79fb\u52a8\u5230\u65b0\u70b9\u4f4d" or direction.startswith("绉诲姩"):
        point = parse_coordinate_text(options.get("point", ""))
        if not point:
            return positions
        target_x, target_y = float(point[0]), float(point[1])
        total_points = max_steps if max_steps >= 2 else 2
        for index in range(1, min(total_points, max_points)):
            ratio = index / (total_points - 1)
            x = base_x + (target_x - base_x) * ratio
            y = base_y + (target_y - base_y) * ratio
            distance_from_base = ((x - base_x) ** 2 + (y - base_y) ** 2) ** 0.5
            if max_distance > 0 and distance_from_base > max_distance:
                break
            positions.append((x, y))
        manual_points = parse_coord_step_manual_points(
            options.get("manual_points", options.get("coord_step_manual_points", {}))
        )
        for index, manual_point in manual_points.items():
            if 0 < index < len(positions):
                positions[index] = manual_point
        return positions

    distance = parse_float_text(options.get("distance", 0), 0.0)
    dx = parse_float_text(options.get("dx", 0), 0.0)
    dy = parse_float_text(options.get("dy", 0), 0.0)
    step_dx, step_dy = coord_step_delta_values(direction, distance, dx, dy)
    if step_dx == 0 and step_dy == 0:
        return positions

    move_count = max_steps if max_steps > 0 else min(10, max_points - 1)
    for index in range(1, min(move_count + 1, max_points)):
        x = base_x + step_dx * index
        y = base_y + step_dy * index
        distance_from_base = ((x - base_x) ** 2 + (y - base_y) ** 2) ** 0.5
        if max_distance > 0 and distance_from_base > max_distance:
            break
        positions.append((x, y))
    return positions
