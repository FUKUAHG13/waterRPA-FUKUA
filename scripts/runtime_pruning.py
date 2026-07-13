"""Conservative PyInstaller payload pruning shared by all release formats."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path


# These optional PyAutoGUI helpers are not used by fukuaRPA. Excluding them at
# graph-analysis time also prevents their tkinter dependency from being frozen.
PYINSTALLER_EXCLUDES = (
    "_tkinter",
    "mouseinfo",
    "pymsgbox",
    "tkinter",
    "PIL.AvifImagePlugin",
    "PIL.ImageCms",
    "PIL.ImageMath",
    "PIL.ImageTk",
    "PIL.WebPImagePlugin",
)


_QT_OPTIONAL_DLLS = {
    "qt6opengl.dll",
    "qt6pdf.dll",
    "qt6qml.dll",
    "qt6qmlmeta.dll",
    "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll",
    "qt6quick.dll",
    "qt6virtualkeyboard.dll",
}
_PIL_OPTIONAL_EXTENSIONS = (
    "_avif.",
    "_imagingcms.",
    "_imagingft.",
    "_imagingmath.",
    "_imagingtk.",
    "_webp.",
)
_CHINESE_QT_TRANSLATION = re.compile(r"_zh_(?:cn|tw)\.qm$", re.IGNORECASE)


def _normalized_destination(entry) -> str:
    return str(entry[0]).replace("\\", "/").lstrip("./").casefold()


def pruning_group(entry) -> str | None:
    """Return the validated pruning group for one PyInstaller TOC entry."""

    destination = _normalized_destination(entry)
    name = destination.rsplit("/", 1)[-1]

    if name.startswith("opencv_videoio_ffmpeg") and name.endswith(".dll"):
        return "opencv_ffmpeg"

    if "/pyside6/" in f"/{destination}":
        if name in _QT_OPTIONAL_DLLS:
            return "qt_quick_qml_pdf_virtual_keyboard"
        if destination.endswith("/plugins/imageformats/qpdf.dll"):
            return "qt_quick_qml_pdf_virtual_keyboard"
        if destination.endswith(
            "/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll"
        ):
            return "qt_quick_qml_pdf_virtual_keyboard"
        if "/translations/" in destination and not _CHINESE_QT_TRANSLATION.search(
            name
        ):
            return "non_chinese_qt_translations"

    if "/pil/" in f"/{destination}" and name.endswith(".pyd"):
        if name.startswith(_PIL_OPTIONAL_EXTENSIONS):
            return "pillow_optional_extensions"

    if name in {"_tkinter.pyd", "tcl86t.dll", "tk86t.dll"}:
        return "tcl_tk"
    if destination.startswith(("_tcl_data/", "_tk_data/", "tcl8/")):
        return "tcl_tk"
    return None


def _prune_toc(entries):
    kept = []
    removed = Counter()
    for entry in entries:
        group = pruning_group(entry)
        if group is None:
            kept.append(entry)
        else:
            removed[group] += 1
    return kept, removed


def apply_runtime_pruning(analysis) -> dict[str, int]:
    """Remove only payload groups covered by source and frozen smoke tests."""

    binaries, binary_counts = _prune_toc(analysis.binaries)
    datas, data_counts = _prune_toc(analysis.datas)
    analysis.binaries[:] = binaries
    analysis.datas[:] = datas
    counts = binary_counts + data_counts
    summary = dict(sorted(counts.items()))
    rendered = ", ".join(f"{name}={count}" for name, count in summary.items())
    print(f"fukuaRPA runtime pruning: {rendered or 'no matching payloads'}")
    return summary


def find_prunable_runtime_paths(root: Path) -> list[str]:
    """Find payloads that should never survive in a verified onedir build."""

    root = root.resolve()
    return [
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold())
        if path.is_file()
        and pruning_group((path.relative_to(root).as_posix(), "", "")) is not None
    ]
