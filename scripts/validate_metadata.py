#!/usr/bin/env python3
"""校验 plugins/*.json 的静态元数据字段（PR 与 CI 使用）。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
VALID_CATEGORIES = {
    "storage",
    "metadata",
    "discovery",
    "automation",
    "subtitle",
    "other",
}
REQUIRED_FIELDS = (
    "plugin_id",
    "display_name",
    "description",
    "author",
    "repo",
    "homepage",
    "categories",
    "official",
)


def validate_plugin(path: Path, data: dict, seen: set[str]) -> list[str]:
    errors: list[str] = []
    name = path.name
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"{name}: 缺少字段 {field}")

    plugin_id = data.get("plugin_id", "")
    if not isinstance(plugin_id, str) or not PLUGIN_ID_RE.match(
        plugin_id
    ) or len(plugin_id) > 64:
        errors.append(f"{name}: plugin_id 非法: {plugin_id!r}")
    elif path.stem != plugin_id:
        errors.append(f"{name}: 文件名应与 plugin_id 一致")
    elif plugin_id in seen:
        errors.append(f"{name}: plugin_id 重复")
    else:
        seen.add(plugin_id)

    repo = data.get("repo", "")
    if not isinstance(repo, str) or not REPO_RE.match(repo):
        errors.append(f"{name}: repo 必须是 owner/name 格式: {repo!r}")

    categories = data.get("categories")
    if not isinstance(categories, list) or not categories:
        errors.append(f"{name}: categories 必须是非空数组")
    else:
        unknown = set(categories) - VALID_CATEGORIES
        if unknown:
            errors.append(f"{name}: 未知分类 {sorted(unknown)}")

    if not isinstance(data.get("official"), bool):
        errors.append(f"{name}: official 必须是布尔值")

    description = data.get("description")
    if not isinstance(description, str) or not 1 <= len(description) <= 200:
        errors.append(f"{name}: description 长度必须在 1-200 之间")

    return errors


def main() -> int:
    errors: list[str] = []
    seen: set[str] = set()
    paths = sorted(PLUGINS_DIR.glob("*.json"))
    if not paths:
        print("plugins/ 下没有元数据文件", file=sys.stderr)
        return 1
    for path in paths:
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as error:
            errors.append(f"{path.name}: JSON 解析失败: {error}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{path.name}: 顶层必须是对象")
            continue
        errors.extend(validate_plugin(path, data, seen))

    if errors:
        for error in errors:
            print(f"校验失败: {error}", file=sys.stderr)
        return 1
    print(f"校验通过，共 {len(seen)} 个插件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
