"""Low-cost scene-change fingerprints used while recognition is backed off."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


SCENE_WAKE_SENSITIVITIES = ("conservative", "balanced", "sensitive")


@dataclass(frozen=True)
class SceneSignature:
    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True)
class SceneChange:
    changed: bool
    peak_percent: float
    top_percent: float
    global_percent: float


_THRESHOLDS = {
    "conservative": (8.0, 1.6, 0.25),
    "balanced": (4.0, 0.8, 0.10),
    "sensitive": (0.4, 0.2, 0.015),
}


def normalize_sensitivity(value) -> str:
    text = str(value or "balanced").strip().lower()
    return text if text in SCENE_WAKE_SENSITIVITIES else "balanced"


def make_scene_signature(image, *, max_width=160, max_height=96):
    """Create a small grayscale fingerprint without importing NumPy/OpenCV."""
    if image is None:
        return None
    work = image.convert("L")
    work.thumbnail(
        (max(8, int(max_width)), max(8, int(max_height))),
        Image.Resampling.BILINEAR,
    )
    if work.width <= 0 or work.height <= 0:
        return None
    return SceneSignature(work.width, work.height, work.tobytes())


def compare_scene_signatures(
    before,
    after,
    *,
    sensitivity="balanced",
    columns=8,
    rows=6,
):
    """Measure global and localized pixel change between two fingerprints."""
    if before is None or after is None:
        return SceneChange(False, 0.0, 0.0, 0.0)
    if before.width != after.width or before.height != after.height:
        return SceneChange(True, 100.0, 100.0, 100.0)
    pixel_count = before.width * before.height
    if pixel_count <= 0 or len(before.pixels) != len(after.pixels):
        return SceneChange(False, 0.0, 0.0, 0.0)

    columns = max(1, min(int(columns), before.width))
    rows = max(1, min(int(rows), before.height))
    tile_sums = [0] * (columns * rows)
    tile_counts = [0] * (columns * rows)
    total = 0
    width = before.width
    height = before.height

    for y in range(height):
        tile_y = min(rows - 1, y * rows // height)
        row_offset = y * width
        for x in range(width):
            delta = abs(before.pixels[row_offset + x] - after.pixels[row_offset + x])
            total += delta
            tile_x = min(columns - 1, x * columns // width)
            tile_index = tile_y * columns + tile_x
            tile_sums[tile_index] += delta
            tile_counts[tile_index] += 1

    tile_percentages = sorted(
        (
            100.0 * value / (255.0 * max(1, tile_counts[index]))
            for index, value in enumerate(tile_sums)
        ),
        reverse=True,
    )
    peak_percent = tile_percentages[0] if tile_percentages else 0.0
    top_count = min(3, len(tile_percentages))
    top_percent = (
        sum(tile_percentages[:top_count]) / top_count if top_count else 0.0
    )
    global_percent = 100.0 * total / (255.0 * pixel_count)
    peak_threshold, top_threshold, global_threshold = _THRESHOLDS[
        normalize_sensitivity(sensitivity)
    ]
    changed = global_percent >= global_threshold or (
        peak_percent >= peak_threshold and top_percent >= top_threshold
    )
    return SceneChange(
        bool(changed),
        float(peak_percent),
        float(top_percent),
        float(global_percent),
    )


def compare_scene_sets(before, after, *, sensitivity="balanced"):
    """Return the strongest change among corresponding recognition regions."""
    previous = tuple(before or ())
    current = tuple(after or ())
    if not previous or not current:
        return SceneChange(False, 0.0, 0.0, 0.0)
    if len(previous) != len(current):
        return SceneChange(True, 100.0, 100.0, 100.0)
    comparisons = [
        compare_scene_signatures(
            first,
            second,
            sensitivity=sensitivity,
        )
        for first, second in zip(previous, current, strict=True)
    ]
    strongest = max(
        comparisons,
        key=lambda result: (
            result.changed,
            result.global_percent,
            result.top_percent,
            result.peak_percent,
        ),
    )
    if any(item.changed for item in comparisons) and not strongest.changed:
        strongest = next(item for item in comparisons if item.changed)
    return strongest
