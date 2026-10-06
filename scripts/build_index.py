#!/usr/bin/env python3
"""从各插件仓库的 GitHub Release 同步版本信息并生成 index.json。

用法：
    GITHUB_TOKEN=xxx python3 scripts/build_index.py

流程：
1. 读取 plugins/*.json（人工维护的静态元数据，含 repo 字段）；
2. 查询 repo 的最新 Release，下载其中的 .zip 资产；
3. 读取包内 manifest.json，校验 plugin_id 与版本号；
4. 回写 latest 字段（version / host_api_version / download_url / sha256 / published_at）；
5. 汇总生成 index.json。

任一插件同步失败时整体失败、不写文件，避免市场出现半截数据。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"
INDEX_PATH = ROOT / "index.json"
TAG_RE = re.compile(r"^v?(\d+\.\d+\.\d+)$")
VALID_CATEGORIES = {
    "storage",
    "metadata",
    "discovery",
    "automation",
    "subtitle",
    "other",
}
USER_AGENT = "sakuramedia-plugin-market"


def github_get(url: str, token: str | None) -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def fail(repo: str, message: str) -> None:
    raise ValueError(f"{repo}: {message}")


def sync_plugin(metadata: dict, token: str | None) -> dict:
    repo = metadata["repo"]
    release = github_get(
        f"https://api.github.com/repos/{repo}/releases/latest", token
    )
    tag = str(release.get("tag_name", "")).strip()
    match = TAG_RE.match(tag)
    if match is None:
        fail(repo, f"无法从 tag 解析三段版本号: {tag!r}")
    version = match.group(1)

    assets = [
        asset
        for asset in release.get("assets", [])
        if str(asset.get("name", "")).lower().endswith(".zip")
    ]
    if not assets:
        fail(repo, f"Release {tag} 没有 .zip 资产")
    asset = assets[0]

    payload = download(asset["browser_download_url"])
    sha256 = hashlib.sha256(payload).hexdigest()
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
    except (KeyError, zipfile.BadZipFile) as error:
        fail(repo, f"插件包缺少合法的 manifest.json: {error}")

    if manifest.get("plugin_id") != metadata["plugin_id"]:
        fail(
            repo,
            "manifest.plugin_id 不匹配: "
            f"{manifest.get('plugin_id')!r} != {metadata['plugin_id']!r}",
        )
    if manifest.get("version") != version:
        fail(
            repo,
            f"manifest.version({manifest.get('version')!r}) 与 tag 版本 {version!r} 不一致",
        )

    metadata["latest"] = {
        "version": version,
        "host_api_version": int(manifest["host_api_version"]),
        "download_url": asset["browser_download_url"],
        "sha256": sha256,
        "published_at": release.get("published_at"),
    }
    return metadata


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
        entries.append((path, metadata))
    if not entries:
        raise ValueError("plugins/ 下没有插件元数据文件")
    return entries


def dump_json(path: Path, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or None
    entries = load_plugin_files()

    for path, metadata in entries:
        plugin_id = metadata["plugin_id"]
        try:
            sync_plugin(metadata, token)
        except (ValueError, urllib.error.URLError) as error:
            print(f"同步失败 -> {error}", file=sys.stderr)
            return 1
        dump_json(path, metadata)
        latest = metadata["latest"]
        print(
            f"同步 {plugin_id}: v{latest['version']} "
            f"(host_api {latest['host_api_version']})"
        )

    plugins = [metadata for _, metadata in entries]
    plugins.sort(key=lambda item: (not item.get("official", False), item["plugin_id"]))
    index = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plugins": plugins,
    }
    dump_json(INDEX_PATH, index)
    print(f"已生成 index.json，共 {len(plugins)} 个插件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
