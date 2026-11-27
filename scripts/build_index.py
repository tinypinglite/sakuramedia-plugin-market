#!/usr/bin/env python3
"""同步插件版本信息并生成 index.json。

用法：
    GITHUB_TOKEN=xxx python3 scripts/build_index.py
    python3 scripts/build_index.py --only sakuramedia_115_provider

流程：
1. 读取 plugins/*.json（人工维护的静态元数据，含 repo / source 字段）；
2. source=external：查询发布仓的 Releases，按 tag 选出该插件最新正式版；
   单插件仓用 ``v<version>``，公开 monorepo 用 ``<plugin_id>-v<version>``；
   source=market：直接使用元数据里已提交的 latest，下载并校验 zip；
3. 读取包内 manifest.json，校验 plugin_id、版本号与 host_api_version；
4. source=external 时回写 latest，并生成 releases/<plugin_id>.json
   （客户端查更新时读这份文件，tag_name 统一成 ``v<version>``）；
5. 把 manifest 里的展示名与简介同步到元数据（display_name / display_name_i18n /
   description / description_i18n）：manifest 给了就以 manifest 为准，没给的文案保留
   市场原值，多语言字典缺席时删掉该键；
6. 汇总生成 index.json。

--only 只同步指定插件；--source 只同步某一类来源（定时任务用它做轻量同步）；
两者都仍用全部插件元数据重建 index.json。任一插件同步失败时不写入任何文件，
避免市场出现半截数据。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"
RELEASES_DIR = ROOT / "releases"
INDEX_PATH = ROOT / "index.json"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
VALID_CATEGORIES = {
    "storage",
    "metadata",
    "discovery",
    "automation",
    "subtitle",
    "other",
}
SOURCE_EXTERNAL = "external"
SOURCE_MARKET = "market"
VALID_SOURCES = {SOURCE_EXTERNAL, SOURCE_MARKET}
USER_AGENT = "sakuramedia-plugin-market"
# 插件身份文案：manifest 是唯一来源，市场只保留 manifest 缺席时的兜底值。
MANIFEST_I18N_FIELDS = ("display_name_i18n", "description_i18n")
# 与 schema/plugin.schema.json 的 description 长度上限一致，超长直接同步失败。
MAX_DESCRIPTION_LENGTH = 200


def _retry(operation, *, attempts: int = 5):
    """下载类操作重试；GitHub 资产偶尔会在 Release 创建后短暂 404。"""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error
            if attempt + 1 == attempts:
                break
            time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def github_get(url: str, token: str | None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def fetch() -> dict:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    return _retry(fetch)


def download(url: str) -> bytes:
    def fetch() -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.read()

    return _retry(fetch)


def fail(identifier: str, message: str) -> None:
    raise ValueError(f"{identifier}: {message}")


def external_tag_version(plugin_id: str, tag: object) -> str | None:
    """从 Release tag 解析版本号：单插件仓 ``v1.2.3``、monorepo ``<id>-v1.2.3``。"""
    if not isinstance(tag, str):
        return None
    value = tag.strip()
    for prefix in (f"{plugin_id}-v", "v"):
        if value.startswith(prefix):
            version = value[len(prefix) :]
            return version if VERSION_RE.fullmatch(version) else None
    return None


def select_external_release(
    releases: list[dict], plugin_id: str
) -> tuple[dict, str]:
    """挑出该插件最新的正式 Release；monorepo 里其他插件的 tag 直接忽略。"""
    best: tuple[tuple[int, int, int], dict, str] | None = None
    for release in releases:
        if not isinstance(release, dict):
            continue
        if release.get("draft") or release.get("prerelease"):
            continue
        version = external_tag_version(plugin_id, release.get("tag_name"))
        if version is None:
            continue
        key = tuple(int(part) for part in version.split("."))
        if best is None or key > best[0]:
            best = (key, release, version)
    if best is None:
        fail(plugin_id, "来源仓没有符合 tag 规范的正式 Release")
    return best[1], best[2]


def write_release_metadata(
    metadata: dict,
    release: dict,
    version: str,
    asset: dict,
    sha256: str,
) -> None:
    """生成 releases/<plugin_id>.json：客户端查更新时读它，tag_name 统一成 v<x.y.z>。"""
    plugin_id = metadata["plugin_id"]
    display_name = metadata.get("display_name") or plugin_id
    dump_json(
        RELEASES_DIR / f"{plugin_id}.json",
        {
            "tag_name": f"v{version}",
            "name": f"{display_name} v{version}",
            "body": release.get("body") or "",
            "published_at": release.get("published_at"),
            "assets": [
                {
                    "name": asset["name"],
                    "browser_download_url": asset["browser_download_url"],
                    "digest": f"sha256:{sha256}",
                }
            ],
        },
    )


def sync_external_plugin(metadata: dict, token: str | None) -> dict:
    """外部源码仓：按 tag 找该插件最新正式版，版本没变就不重复下载 zip。"""
    repo = metadata["repo"]
    plugin_id = metadata["plugin_id"]
    releases = github_get(
        f"https://api.github.com/repos/{repo}/releases?per_page=100", token
    )
    if not isinstance(releases, list):
        fail(repo, "Releases 接口没有返回数组")
    release, version = select_external_release(releases, plugin_id)

    assets = [
        asset
        for asset in release.get("assets", [])
        if str(asset.get("name", "")).lower().endswith(".zip")
    ]
    if not assets:
        fail(repo, f"Release {release.get('tag_name')!r} 没有 .zip 资产")
    asset = assets[0]
    download_url = asset.get("browser_download_url")
    latest = metadata.get("latest")
    if not isinstance(latest, dict):
        latest = {}

    if latest.get("version") == version and latest.get("download_url") == download_url:
        host_api_version = latest.get("host_api_version")
        sha256 = latest.get("sha256")
    else:
        payload = download(download_url)
        sha256 = hashlib.sha256(payload).hexdigest()
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, zipfile.BadZipFile) as error:
            fail(repo, f"插件包缺少合法的 manifest.json: {error}")
            raise
        if manifest.get("plugin_id") != plugin_id:
            fail(
                repo,
                "manifest.plugin_id 不匹配: "
                f"{manifest.get('plugin_id')!r} != {plugin_id!r}",
            )
        if manifest.get("version") != version:
            fail(
                repo,
                f"manifest.version({manifest.get('version')!r}) 与 tag 版本 "
                f"{version!r} 不一致",
            )
        host_api_version = manifest["host_api_version"]
        apply_manifest_text(metadata, manifest, repo)

    metadata["latest"] = {
        "version": version,
        "host_api_version": int(host_api_version),
        "download_url": download_url,
        "sha256": sha256,
        "published_at": release.get("published_at"),
    }
    write_release_metadata(metadata, release, version, asset, sha256)
    return metadata


def require_market_latest(metadata: dict) -> dict:
    """官方插件的 latest 由发版 Action 写入；这里只做形状校验。"""
    plugin_id = metadata["plugin_id"]
    latest = metadata.get("latest")
    if not isinstance(latest, dict):
        fail(plugin_id, "source=market 必须已有 latest")
    required = (
        "version",
        "host_api_version",
        "download_url",
        "sha256",
        "published_at",
    )
    missing = [field for field in required if field not in latest]
    if missing:
        fail(plugin_id, f"latest 缺少字段 {missing}")
    if not isinstance(latest["version"], str) or not VERSION_RE.fullmatch(
        latest["version"]
    ):
        fail(plugin_id, f"latest.version 不是三段版本号: {latest['version']!r}")
    if not isinstance(latest["host_api_version"], int):
        fail(plugin_id, "latest.host_api_version 必须是整数")
    if not isinstance(latest["download_url"], str) or not latest["download_url"]:
        fail(plugin_id, "latest.download_url 必须是非空字符串")
    if not isinstance(latest["sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", latest["sha256"]
    ):
        fail(plugin_id, "latest.sha256 必须是 64 位小写十六进制")
    return latest


def sync_market_plugin(metadata: dict) -> dict:
    """官方插件：下载市场仓 Release 资产，并校验已提交的 latest 是否自洽。"""
    plugin_id = metadata["plugin_id"]
    latest = require_market_latest(metadata)
    payload = download(latest["download_url"])
    sha256 = hashlib.sha256(payload).hexdigest()
    if sha256 != latest["sha256"]:
        fail(
            plugin_id,
            f"latest.sha256 与下载内容不一致: {latest['sha256']} != {sha256}",
        )
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
    except (KeyError, zipfile.BadZipFile) as error:
        fail(plugin_id, f"插件包缺少合法的 manifest.json: {error}")
        raise

    if manifest.get("plugin_id") != plugin_id:
        fail(
            plugin_id,
            "manifest.plugin_id 不匹配: "
            f"{manifest.get('plugin_id')!r} != {plugin_id!r}",
        )
    if manifest.get("version") != latest["version"]:
        fail(
            plugin_id,
            f"manifest.version({manifest.get('version')!r}) 与 latest.version "
            f"{latest['version']!r} 不一致",
        )
    try:
        manifest_host_api = int(manifest["host_api_version"])
    except (KeyError, TypeError, ValueError) as error:
        fail(plugin_id, f"manifest.host_api_version 非法: {error}")
        raise
    if manifest_host_api != latest["host_api_version"]:
        fail(
            plugin_id,
            f"manifest.host_api_version({manifest_host_api}) 与 "
            f"latest.host_api_version({latest['host_api_version']}) 不一致",
        )

    apply_manifest_text(metadata, manifest, plugin_id)
    return metadata


def _i18n_map(value: object) -> dict[str, str]:
    """把 manifest 的 *_i18n 规整成 {语言标签: 文本}；非法项直接丢弃。"""
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for locale, text in value.items():
        if not isinstance(locale, str) or not isinstance(text, str):
            continue
        key = locale.strip()
        content = text.strip()
        if key and content:
            result[key] = content
    return result


def apply_manifest_text(metadata: dict, manifest: dict, identifier: str) -> None:
    """把插件 manifest 的展示文案搬进市场元数据。

    插件 manifest 是展示名与简介的唯一事实源：manifest 给了就以 manifest 为准，
    没给就保留市场原值（没做多语言的插件不会因此丢掉中文简介）。多语言字典在
    manifest 里缺席时直接删键，避免索引里留下上一版的过期翻译。
    """
    display_name = manifest.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        metadata["display_name"] = display_name.strip()

    description = manifest.get("description")
    if isinstance(description, str) and description.strip():
        content = description.strip()
        if len(content) > MAX_DESCRIPTION_LENGTH:
            fail(
                identifier,
                f"manifest.description 超过 {MAX_DESCRIPTION_LENGTH} 字: {content!r}",
            )
        metadata["description"] = content

    for field in MANIFEST_I18N_FIELDS:
        translations = _i18n_map(manifest.get(field))
        if translations:
            metadata[field] = translations
        else:
            metadata.pop(field, None)


def load_plugin_files() -> list[tuple[Path, dict]]:
    entries: list[tuple[Path, dict]] = []
    for path in sorted(PLUGINS_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            metadata = json.load(handle)
        plugin_id = metadata.get("plugin_id")
        if not plugin_id:
            raise ValueError(f"{path.name}: 缺少 plugin_id")
        if path.stem != plugin_id:
            raise ValueError(f"{path.name}: 文件名应与 plugin_id 一致")
        unknown = set(metadata.get("categories", [])) - VALID_CATEGORIES
        if unknown:
            raise ValueError(f"{path.name}: 未知分类 {sorted(unknown)}")
        source = metadata.get("source", SOURCE_EXTERNAL)
        if source not in VALID_SOURCES:
            raise ValueError(f"{path.name}: 未知 source {source!r}")
        entries.append((path, metadata))
    if not entries:
        raise ValueError("plugins/ 下没有插件元数据文件")
    return entries


def dump_json(path: Path, data: dict) -> bool:
    """原子写入文件；内容无变化时不写并返回 False。"""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        default=None,
        help="只同步指定 plugin_id，但仍用全部插件元数据重建 index.json",
    )
    parser.add_argument(
        "--source",
        default=None,
        choices=sorted(VALID_SOURCES),
        help="只同步某一类来源的插件（存量 latest 原样保留）",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or None
    entries = load_plugin_files()
    selected = entries
    if args.source:
        selected = [
            (path, metadata)
            for path, metadata in selected
            if metadata.get("source", SOURCE_EXTERNAL) == args.source
        ]
    if args.only:
        selected = [
            (path, metadata)
            for path, metadata in selected
            if metadata["plugin_id"] == args.only
        ]
        if not selected:
            print(f"未找到插件: {args.only}", file=sys.stderr)
            return 1

    synced: list[tuple[Path, dict]] = []
    for path, metadata in selected:
        plugin_id = metadata["plugin_id"]
        source = metadata.get("source", SOURCE_EXTERNAL)
        try:
            if source == SOURCE_MARKET:
                sync_market_plugin(metadata)
            else:
                sync_external_plugin(metadata, token)
        except (ValueError, KeyError, urllib.error.URLError, TimeoutError) as error:
            print(f"同步失败 -> {error}", file=sys.stderr)
            return 1
        synced.append((path, metadata))

    for path, metadata in synced:
        plugin_id = metadata["plugin_id"]
        latest = metadata["latest"]
        changed = dump_json(path, metadata)
        status = "已更新" if changed else "无变化"
        print(
            f"同步 {plugin_id}: v{latest['version']} "
            f"(host_api {latest['host_api_version']}) [{status}]"
        )

    plugins = [metadata for _, metadata in entries]
    plugins.sort(key=lambda item: (not item.get("official", False), item["plugin_id"]))

    previous_updated_at = None
    if INDEX_PATH.exists():
        try:
            previous = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
        if (
            previous.get("schema_version") == 1
            and previous.get("plugins") == plugins
        ):
            previous_updated_at = previous.get("updated_at")

    index = {
        "schema_version": 1,
        "updated_at": previous_updated_at
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plugins": plugins,
    }
    if dump_json(INDEX_PATH, index):
        print("index.json 已更新")
    else:
        print("index.json 无变化")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
