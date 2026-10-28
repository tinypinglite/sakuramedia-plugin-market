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
# 多语言字典字段：缺失是合法的（插件不做多语言），存在时必须覆盖这两种语言。
I18N_FIELDS = ("display_name_i18n", "description_i18n")
REQUIRED_LOCALES = ("zh-CN", "en")


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

    for field in I18N_FIELDS:
        errors.extend(_validate_i18n_map(name, field, data.get(field)))

    return errors


def _validate_i18n_map(name: str, field: str, value: object) -> list[str]:
    """校验多语言字典：必须是 {语言标签: 非空字符串}。

    字典整体缺失是合法的（插件不做多语言）；存在时两个语言都要有，避免英文
    界面因为漏了 zh-CN 或 en 而露出另一种语言的文案。
    """
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"{name}: {field} 必须是对象"]
    errors: list[str] = []
    for locale, text in value.items():
        if not isinstance(locale, str) or not locale.strip():
            errors.append(f"{name}: {field} 的语言标签必须是非空字符串")
            continue
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{name}: {field}.{locale} 必须是非空字符串")
    missing = [locale for locale in REQUIRED_LOCALES if locale not in value]
    if missing:
        errors.append(f"{name}: {field} 缺少语言 {missing}")
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
