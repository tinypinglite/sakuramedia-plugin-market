#!/usr/bin/env python3
"""Package skills and write the skills index consumed by the app.

Source of truth lives in `skills/<name>/`; this script writes the packaged
`skills/<name>-<version>.zip` files and `skills/index.json` next to them, so run
it before committing any skill change.

Rules stay intentionally small:

- `skill.json` name must equal the directory name, and names must be unique.
- The `sakuramedia-` name prefix is reserved for official skills.
- Official skills always publish `author: SakuraMedia`; nobody else may use it.
- A version that is already published with different content must be bumped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PUBLIC_BASE_URL = (
    "https://tinypinglite.github.io/sakuramedia-plugin-market/skills"
)
OFFICIAL_SKILLS = {"sakuramedia-acquire", "sakuramedia-skill-builder"}
OFFICIAL_AUTHOR = "SakuraMedia"
OFFICIAL_NAME_PREFIX = "sakuramedia-"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SKIP_NAMES = {".DS_Store", "__pycache__", ".pytest_cache", "data"}


class PackageError(RuntimeError):
    pass


def _load_manifest(skill_dir: Path) -> dict[str, Any]:
    manifest_path = skill_dir / "skill.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PackageError(f"{skill_dir.name}: missing skill.json") from exc
    except json.JSONDecodeError as exc:
        raise PackageError(f"{skill_dir.name}: invalid skill.json") from exc
    if not isinstance(manifest, dict):
        raise PackageError(f"{skill_dir.name}: skill.json must be an object")

    name = str(manifest.get("name") or "").strip()
    version = str(manifest.get("version") or "").strip()
    if not NAME_RE.fullmatch(name):
        raise PackageError(f"{skill_dir.name}: name must be lowercase-kebab")
    if name != skill_dir.name:
        raise PackageError(f"{skill_dir.name}: manifest name must match folder")
    if not VERSION_RE.fullmatch(version):
        raise PackageError(f"{skill_dir.name}: version must be x.y.z")
    if not (skill_dir / "SKILL.md").is_file():
        raise PackageError(f"{skill_dir.name}: missing SKILL.md")
    entrypoint = manifest.get("entrypoint")
    if entrypoint and not (skill_dir / str(entrypoint)).is_file():
        raise PackageError(f"{skill_dir.name}: missing entrypoint {entrypoint}")

    official = name in OFFICIAL_SKILLS
    if name.startswith(OFFICIAL_NAME_PREFIX) and not official:
        raise PackageError(
            f"{skill_dir.name}: the {OFFICIAL_NAME_PREFIX}* prefix is reserved "
            "for official skills"
        )
    author = str(manifest.get("author") or "").strip()
    if official:
        manifest["author"] = OFFICIAL_AUTHOR
    elif not author:
        raise PackageError(f"{skill_dir.name}: community skills need an author")
    elif author.casefold() == OFFICIAL_AUTHOR.casefold():
        raise PackageError(
            f"{skill_dir.name}: the author name {OFFICIAL_AUTHOR} is reserved"
        )
    return manifest


def _iter_skill_files(skill_dir: Path):
    for path in sorted(skill_dir.rglob("*")):
        if path.is_dir():
            continue
        if any(part in SKIP_NAMES for part in path.parts):
            continue
        if path.name.endswith((".pyc", ".pyo")):
            continue
        yield path


def _content_digest(skill_dir: Path) -> str:
    """按源文件内容算摘要：与 zip 打包细节（mtime、zlib 版本）无关。"""
    digest = hashlib.sha256()
    for path in _iter_skill_files(skill_dir):
        digest.update(f"{path.relative_to(skill_dir)}\0".encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _zip_info(relative: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o644 << 16
    return info


def _build_zip(skill_dir: Path, output_dir: Path, version: str) -> tuple[str, str]:
    zip_name = f"{skill_dir.name}-{version}.zip"
    archive_path = output_dir / zip_name
    buffer_path = output_dir / f"{zip_name}.tmp"
    with zipfile.ZipFile(
        buffer_path, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in _iter_skill_files(skill_dir):
            archive.writestr(
                _zip_info(f"{skill_dir.name}/{path.relative_to(skill_dir)}"),
                path.read_bytes(),
            )
    digest = hashlib.sha256(buffer_path.read_bytes()).hexdigest()
    buffer_path.replace(archive_path)
    return zip_name, digest


def _load_previous_index(index_path: Path) -> dict[str, dict[str, Any]]:
    if not index_path.is_file():
        return {}
    try:
        previous = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = previous.get("skills") if isinstance(previous, dict) else None
    if not isinstance(entries, list):
        return {}
    return {
        str(entry["name"]): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }


def _stable_updated_at(index_path: Path, skills: list[dict[str, Any]]) -> str:
    """重复发布相同内容时保留原时间，避免只改时间戳的空提交。"""
    if index_path.is_file():
        try:
            previous = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if (
            isinstance(previous, dict)
            and previous.get("schema_version") == 1
            and previous.get("skills") == skills
            and isinstance(previous.get("updated_at"), str)
        ):
            return previous["updated_at"]
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_skills(
    *,
    skills_dir: Path,
    output_dir: Path,
    public_base_url: str,
) -> dict[str, Any]:
    if not skills_dir.is_dir():
        raise PackageError(f"skills directory not found: {skills_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    previous = _load_previous_index(output_dir / "index.json")
    skills: list[dict[str, Any]] = []
    seen: set[str] = set()
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
            continue
        if not (skill_dir / "skill.json").is_file():
            continue
        manifest = _load_manifest(skill_dir)
        name = str(manifest["name"])
        if name in seen:
            raise PackageError(f"duplicate skill name: {name}")
        seen.add(name)
        version = str(manifest["version"])
        content_digest = _content_digest(skill_dir)
        zip_name = f"{name}-{version}.zip"
        published = previous.get(name)
        if published and published.get("version") == version:
            if published.get("content_sha256") != content_digest:
                raise PackageError(
                    f"{name}: version {version} is already published with "
                    "different content; bump skill.json version"
                )
        if (
            published
            and published.get("version") == version
            and (output_dir / zip_name).is_file()
            and isinstance(published.get("sha256"), str)
        ):
            # 内容一致：复用已有的 zip，避免重复打包产生无意义的差异。
            digest = published["sha256"]
        else:
            _, digest = _build_zip(skill_dir, output_dir, version)
        skills.append(
            {
                "name": name,
                "author": manifest["author"],
                "official": name in OFFICIAL_SKILLS,
                "content_sha256": content_digest,
                "display_name": manifest.get("display_name") or name,
                "display_name_en": manifest.get("display_name_en")
                or manifest.get("display_name")
                or name,
                "description": manifest.get("description") or "",
                "description_en": manifest.get("description_en")
                or manifest.get("description")
                or "",
                "version": version,
                "download_url": f"{public_base_url.rstrip('/')}/{zip_name}",
                "sha256": digest,
            }
        )
    if not skills:
        raise PackageError("no skills found")

    catalog = {
        "schema_version": 1,
        "updated_at": _stable_updated_at(output_dir / "index.json", skills),
        "skills": skills,
    }
    (output_dir / "index.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-dir", default="skills")
    parser.add_argument("--output", default="skills")
    parser.add_argument("--public-base-url", default=DEFAULT_PUBLIC_BASE_URL)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output)
    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    try:
        catalog = build_skills(
            skills_dir=Path(args.skills_dir),
            output_dir=output_dir,
            public_base_url=args.public_base_url,
        )
    except PackageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(catalog, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
