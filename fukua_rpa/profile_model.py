"""Qt-independent ordered profile collection used by the main window."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

from .config_schema import default_profile_config, migrate_profiles
from .constants import MAX_PROFILES


@dataclass
class ProfileCollection:
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    current_name: str = "默认方案"

    def replace(self, profiles: Mapping[str, Any], current_name: str | None = None) -> bool:
        migrated, changed = migrate_profiles(profiles)
        if not migrated:
            migrated = {"默认方案": default_profile_config()}
            changed = True
        self.profiles = migrated
        requested = str(current_name or "")
        self.current_name = requested if requested in migrated else next(iter(migrated))
        return changed

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self.profiles)

    def select(self, name: str) -> dict[str, Any]:
        if name not in self.profiles:
            raise KeyError(f"方案不存在：{name}")
        self.current_name = name
        return self.profiles[name]

    def create(self, name: str, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
        name = str(name).strip()
        if not name:
            raise ValueError("方案名称不能为空")
        if name in self.profiles:
            raise ValueError("方案名称已存在")
        if len(self.profiles) >= MAX_PROFILES:
            raise ValueError(f"方案数量已达到上限 {MAX_PROFILES}")
        value = default_profile_config() if config is None else copy.deepcopy(dict(config))
        migrated, _changed = migrate_profiles({name: value})
        self.profiles[name] = migrated[name]
        self.current_name = name
        return self.profiles[name]

    def rename(self, new_name: str) -> None:
        new_name = str(new_name).strip()
        if not new_name:
            raise ValueError("方案名称不能为空")
        if new_name == self.current_name:
            return
        if new_name in self.profiles:
            raise ValueError("方案名称已存在")
        items = []
        for name, config in self.profiles.items():
            items.append((new_name if name == self.current_name else name, config))
        self.profiles = dict(items)
        self.current_name = new_name

    def delete_current(self) -> str:
        if len(self.profiles) <= 1:
            raise ValueError("至少需要保留一个方案")
        removed = self.current_name
        names = list(self.profiles)
        index = names.index(removed)
        self.profiles.pop(removed)
        remaining = list(self.profiles)
        self.current_name = remaining[min(index, len(remaining) - 1)]
        return removed

    def move_current(self, offset: int) -> int:
        names = list(self.profiles)
        index = names.index(self.current_name)
        target = min(max(index + int(offset), 0), len(names) - 1)
        if target == index:
            return index
        names[index], names[target] = names[target], names[index]
        self.profiles = {name: self.profiles[name] for name in names}
        return target
