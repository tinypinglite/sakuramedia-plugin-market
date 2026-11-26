#!/usr/bin/env python3
"""Plan and scaffold new SakuraMedia agent skills.

The tool only needs the backend's own description of itself:

* `GET /status` for the backend version,
* `GET /openapi.json` for the endpoint surface.

It classifies every endpoint by side effect so generated skills can force an
explicit `--confirm` on anything that changes server state.

Commands:
    describe  list endpoints with a side-effect classification
    scaffold  write a skill package skeleton for chosen endpoints
    validate  check a generated skill directory against the house rules
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pprint
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, parse, request

BASE_URL_ENV = "SAKURAMEDIA_BASE_URL"
API_KEY_ENV = "SAKURAMEDIA_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 30.0
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# POST endpoints whose semantics are read-only: no local state is written.
READ_LIKE: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/movies/search/parse-number"),
        ("POST", "/media-tags/preview"),
        ("POST", "/download-selection-policy/preview"),
    }
)

SIDE_EFFECT_LABELS = {
    "read": "read",
    "read_like": "read-like",
    "write": "WRITE",
}


class BuilderError(RuntimeError):
    """A user-facing failure."""


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    side_effect: str
    summary: str
    path_params: tuple[str, ...] = ()
    query_params: tuple[str, ...] = ()
    body_required: tuple[str, ...] = ()
    body_optional: tuple[str, ...] = ()

    @property
    def command(self) -> str:
        return _command_name(self.method, self.path)

    @property
    def requires_confirm(self) -> bool:
        return self.side_effect == "write"


@dataclass
class Schema:
    backend_version: str = ""
    endpoints: list[Endpoint] = field(default_factory=list)

    def find(self, method: str, path: str) -> Endpoint:
        for endpoint in self.endpoints:
            if endpoint.method == method and endpoint.path == path:
                return endpoint
        raise BuilderError(f"endpoint not found in schema: {method} {path}")

    def filter(self, needle: str | None, method: str | None) -> list[Endpoint]:
        result = self.endpoints
        if method:
            result = [item for item in result if item.method == method.upper()]
        if needle:
            lowered = needle.lower()
            result = [
                item
                for item in result
                if lowered in item.path.lower() or lowered in item.command
            ]
        order = {"read": 0, "read_like": 1, "write": 2}
        return sorted(result, key=lambda item: (order[item.side_effect], item.path))


def _command_name(method: str, path: str) -> str:
    parts = [method.lower()]
    for segment in path.split("/"):
        if not segment:
            continue
        if segment.startswith("{") and segment.endswith("}"):
            parts.extend(("by", segment[1:-1]))
        else:
            parts.append(segment.replace("-", "_"))
    return "_".join(parts)


def _classify(method: str, path: str) -> str:
    if method == "GET":
        return "read"
    if (method, path) in READ_LIKE:
        return "read_like"
    if path.endswith("/test"):
        # Probes reach external services but do not change local state.
        return "read_like"
    return "write"


def _resolve_ref(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if not isinstance(ref, str):
        return node
    name = ref.rsplit("/", 1)[-1]
    return schema.get("components", {}).get("schemas", {}).get(name, {})


def _parse_schema(document: dict[str, Any]) -> Schema:
    schema = Schema()
    for path, operations in document.get("paths", {}).items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            path_params: list[str] = []
            query_params: list[str] = []
            for parameter in operation.get("parameters", []):
                location = parameter.get("in")
                name = parameter.get("name")
                if not isinstance(name, str):
                    continue
                if location == "path":
                    path_params.append(name)
                elif location == "query":
                    query_params.append(name)
            body_required: list[str] = []
            body_optional: list[str] = []
            body = operation.get("requestBody", {}).get("content", {})
            json_body = body.get("application/json", {}).get("schema")
            if isinstance(json_body, dict):
                resolved = _resolve_ref(document, json_body)
                required = set(resolved.get("required", []))
                for name in resolved.get("properties", {}):
                    (body_required if name in required else body_optional).append(name)
            schema.endpoints.append(
                Endpoint(
                    method=method.upper(),
                    path=path,
                    side_effect=_classify(method.upper(), path),
                    summary=str(operation.get("summary") or ""),
                    path_params=tuple(path_params),
                    query_params=tuple(query_params),
                    body_required=tuple(sorted(body_required)),
                    body_optional=tuple(sorted(body_optional)),
                )
            )
    return schema


def _request_json(url: str, api_key: str, timeout: float) -> Any:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request_object = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(request_object, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise BuilderError(f"{url} returned HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise BuilderError(f"cannot reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise BuilderError(f"{url} timed out") from exc
    except json.JSONDecodeError as exc:
        raise BuilderError(f"{url} did not return JSON") from exc


def _connection() -> tuple[str, str]:
    base_url = os.environ.get(BASE_URL_ENV, "").strip().rstrip("/")
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not base_url:
        raise BuilderError(
            f"Missing {BASE_URL_ENV}. Every Sakuramedia skill uses the same base url."
        )
    parsed = parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BuilderError("base_url must be a full http/https URL")
    return base_url, api_key


def load_schema(schema_file: Path | None, timeout: float) -> Schema:
    if schema_file is not None:
        try:
            document = json.loads(schema_file.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise BuilderError(f"schema file not found: {schema_file}") from exc
        except json.JSONDecodeError as exc:
            raise BuilderError(f"schema file is not valid JSON: {schema_file}") from exc
        backend_version = ""
    else:
        base_url, api_key = _connection()
        document = _request_json(f"{base_url}/openapi.json", api_key, timeout)
        backend_version = ""
        if api_key:
            status = _request_json(f"{base_url}/status", api_key, timeout)
            if isinstance(status, dict):
                backend_version = str(status.get("backend_version") or "")
    schema = _parse_schema(document)
    schema.backend_version = backend_version
    if not schema.endpoints:
        raise BuilderError("schema contains no endpoints")
    return schema


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_describe(args: argparse.Namespace) -> int:
    schema = load_schema(args.schema, args.timeout)
    selected = schema.filter(args.filter, args.method)
    if args.json:
        _emit(
            {
                "backend_version": schema.backend_version,
                "endpoints": [
                    {
                        "command": item.command,
                        "method": item.method,
                        "path": item.path,
                        "side_effect": item.side_effect,
                        "requires_confirm": item.requires_confirm,
                        "path_params": list(item.path_params),
                        "query_params": list(item.query_params),
                        "body_required": list(item.body_required),
                        "body_optional": list(item.body_optional),
                    }
                    for item in selected
                ],
            }
        )
        return 0
    if schema.backend_version:
        print(f"backend_version: {schema.backend_version}")
    print(f"endpoints: {len(selected)}")
    for item in selected:
        details: list[str] = []
        if item.path_params:
            details.append("path: " + ", ".join(item.path_params))
        if item.query_params:
            details.append("query: " + ", ".join(item.query_params))
        if item.body_required:
            details.append("body*: " + ", ".join(item.body_required))
        if item.body_optional:
            details.append("body: " + ", ".join(item.body_optional))
        confirm = " --confirm required" if item.requires_confirm else ""
        suffix = f"  [{'; '.join(details)}]" if details else ""
        print(
            f"{SIDE_EFFECT_LABELS[item.side_effect]:9} "
            f"{item.method:6} {item.path}{confirm}{suffix}"
        )
    return 0


SCRIPT_TEMPLATE = '''#!/usr/bin/env python3
"""{description}"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib import error, parse, request

BASE_URL_ENV = "SAKURAMEDIA_BASE_URL"
API_KEY_ENV = "SAKURAMEDIA_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 30.0

# Generated from the backend schema: one entry per endpoint.
COMMANDS: list[dict[str, Any]] = {commands}


class SkillError(RuntimeError):
    """A user-facing failure."""


def _connection() -> tuple[str, str]:
    base_url = os.environ.get(BASE_URL_ENV, "").strip().rstrip("/")
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not base_url or not api_key:
        raise SkillError(
            f"Missing connection details. Provide {{BASE_URL_ENV}} and "
            f"{{API_KEY_ENV}} for this process; every Sakuramedia skill uses "
            "the same values."
        )
    parsed = parse.urlsplit(base_url)
    if parsed.scheme not in {{"http", "https"}} or not parsed.netloc:
        raise SkillError("base_url must be a full http/https URL")
    return base_url, api_key


def _call(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None,
    body: dict[str, Any] | None,
    timeout: float,
) -> Any:
    base_url, api_key = _connection()
    url = base_url + path
    if params:
        url = f"{{url}}?{{parse.urlencode(params, doseq=True)}}"
    payload = None
    headers = {{
        "Accept": "application/json",
        "Accept-Language": "en",
        "Authorization": f"Bearer {{api_key}}",
    }}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request_object = request.Request(url, data=payload, headers=headers, method=method)
    try:
        with request.urlopen(request_object, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        raise SkillError(
            f"{{method}} {{path}} returned HTTP {{exc.code}}: "
            f"{{exc.read().decode('utf-8', 'replace')}}"
        ) from exc
    except error.URLError as exc:
        raise SkillError(f"Cannot reach the backend: {{exc.reason}}") from exc
    except TimeoutError as exc:
        raise SkillError(f"Request timed out: {{path}} — check state before retrying") from exc
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SkillError(f"Backend returned invalid JSON for {{path}}") from exc


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _spec(name: str) -> dict[str, Any]:
    for command in COMMANDS:
        if command["name"] == name:
            return command
    raise SkillError(f"unknown command: {{name}}")


def cmd_check(args: argparse.Namespace) -> int:
    health = _call("GET", "/healthz", params=None, body=None, timeout=args.timeout)
    status = _call("GET", "/status", params=None, body=None, timeout=args.timeout)
    _emit({{"ok": True, "health": health, "status": status}})
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    spec = _spec(args.command)
    if spec["side_effect"] == "write" and not args.confirm:
        raise SkillError(
            f"{{args.command}} changes server state. Ask the user to confirm, "
            "then rerun with --confirm."
        )
    path = spec["path"]
    for name in spec["path_params"]:
        value = getattr(args, name)
        if value in (None, ""):
            raise SkillError(f"missing --{{name.replace('_', '-')}}")
        path = path.replace("{{" + name + "}}", parse.quote(str(value), safe=""))
    params: dict[str, Any] = {{}}
    for name in spec["query_params"]:
        value = getattr(args, name)
        if value is not None:
            params[name] = value
    body = None
    if spec["body_required"] or spec["body_optional"]:
        if args.body_json:
            try:
                body = json.loads(args.body_json)
            except json.JSONDecodeError as exc:
                raise SkillError("--body-json must be valid JSON") from exc
        else:
            body = {{}}
        if not isinstance(body, dict):
            raise SkillError("--body-json must be a JSON object")
        missing = [name for name in spec["body_required"] if name not in body]
        if missing:
            raise SkillError("missing body fields: " + ", ".join(missing))
    _emit(_call(spec["method"], path, params=params, body=body, timeout=args.timeout))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="{description}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Validate the connection")
    check.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    check.set_defaults(handler=cmd_check)

    for spec in COMMANDS:
        command = subparsers.add_parser(spec["name"], help=spec["summary"] or spec["path"])
        command.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
        for name in spec["path_params"]:
            command.add_argument(f"--{{name.replace('_', '-')}}", dest=name, required=True)
        for name in spec["query_params"]:
            command.add_argument(f"--{{name.replace('_', '-')}}", dest=name, default=None)
        if spec["body_required"] or spec["body_optional"]:
            command.add_argument("--body-json", default=None)
        if spec["side_effect"] == "write":
            command.add_argument("--confirm", action="store_true")
        command.set_defaults(handler=cmd_call)
        command.set_defaults(command=spec["name"])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except SkillError as exc:
        _emit({{"ok": False, "error": {{"message": str(exc)}}}})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
'''

SKILL_TEMPLATE = """---
name: {name}
description: {description} Use it when the user asks for this capability on their SakuraMedia server.
---

# {display_name}

{description}

Reply in the user's language.

## Connection

Two environment variables, shared by every Sakuramedia skill:

- `SAKURAMEDIA_BASE_URL`
- `SAKURAMEDIA_API_KEY`

Never print the API key. Verify the connection first:

```bash
python3 scripts/{script} check
```

## Commands

`python3 scripts/{script} <command>`

{command_docs}

## Rules

- Commands marked **write** change server state. Ask the user, then rerun the exact command with `--confirm`.
- After a timeout, check state instead of replaying the call.
- Never paste the API key, full magnet links or large raw JSON payloads into replies.
"""


def _command_docs(endpoints: list[Endpoint]) -> str:
    lines: list[str] = []
    for endpoint in endpoints:
        parts: list[str] = []
        if endpoint.path_params:
            parts.append(
                "path: "
                + ", ".join(
                    f"--{name.replace('_', '-')}" for name in endpoint.path_params
                )
            )
        if endpoint.query_params:
            parts.append("query: " + ", ".join(endpoint.query_params))
        if endpoint.body_required:
            parts.append("body (required): " + ", ".join(endpoint.body_required))
        if endpoint.body_optional:
            parts.append("body (optional): " + ", ".join(endpoint.body_optional))
        marker = "**write**, needs `--confirm`" if endpoint.requires_confirm else "read"
        detail = f" — {'; '.join(parts)}" if parts else ""
        lines.append(
            f"- `{endpoint.command}` — {endpoint.method} `{endpoint.path}` "
            f"({marker}){detail}"
        )
    lines.append("")
    lines.append(
        "Write commands take `--body-json '<json>'` when the endpoint expects a request body."
    )
    return "\n".join(lines)


def _commands_literal(endpoints: list[Endpoint]) -> str:
    payload = [
        {
            "name": endpoint.command,
            "method": endpoint.method,
            "path": endpoint.path,
            "summary": endpoint.summary,
            "side_effect": endpoint.side_effect,
            "path_params": list(endpoint.path_params),
            "query_params": list(endpoint.query_params),
            "body_required": list(endpoint.body_required),
            "body_optional": list(endpoint.body_optional),
        }
        for endpoint in endpoints
    ]
    return pprint.pformat(payload, indent=4, width=88, sort_dicts=False)


def cmd_scaffold(args: argparse.Namespace) -> int:
    if not NAME_RE.fullmatch(args.name):
        raise BuilderError("--name must be lowercase-kebab (a-z, 0-9, -)")
    if not args.endpoint:
        raise BuilderError("pass at least one --endpoint METHOD:/path")
    schema = load_schema(args.schema, args.timeout)
    endpoints: list[Endpoint] = []
    for raw in args.endpoint:
        method, _, path = raw.partition(":")
        if not method or not path:
            raise BuilderError(f"--endpoint must be METHOD:/path, got {raw!r}")
        endpoints.append(schema.find(method.strip().upper(), path.strip()))
    script_name = args.name.replace("-", "_") + ".py"
    output = Path(args.output) / args.name
    if output.exists() and not args.force:
        raise BuilderError(f"{output} already exists; pass --force to overwrite")
    (output / "scripts").mkdir(parents=True, exist_ok=True)
    (output / "skill.json").write_text(
        json.dumps(
            {
                "name": args.name,
                "author": args.author,
                "display_name": args.display_name or args.name,
                "version": "0.1.0",
                "description": args.description,
                "entrypoint": f"scripts/{script_name}",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(
            name=args.name,
            description=args.description,
            display_name=args.display_name or args.name,
            script=script_name,
            command_docs=_command_docs(endpoints),
        ),
        encoding="utf-8",
    )
    script_path = output / "scripts" / script_name
    script_path.write_text(
        SCRIPT_TEMPLATE.format(
            description=args.description,
            commands=_commands_literal(endpoints),
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    _emit(
        {
            "ok": True,
            "skill_dir": str(output),
            "commands": [item.command for item in endpoints],
            "write_commands": [
                item.command for item in endpoints if item.requires_confirm
            ],
        }
    )
    return 0


def _load_commands(source: str) -> list[dict[str, Any]] | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            target: ast.expr | None = node.target
        elif isinstance(node, ast.Assign):
            target = node.targets[0] if len(node.targets) == 1 else None
        else:
            continue
        if not (isinstance(target, ast.Name) and target.id == "COMMANDS"):
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError:
            return None
        return value if isinstance(value, list) else None
    return None


def cmd_validate(args: argparse.Namespace) -> int:
    skill_dir = Path(args.skill_dir)
    problems: list[str] = []
    manifest_path = skill_dir / "skill.json"
    if not manifest_path.is_file():
        raise BuilderError(f"missing {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    name = str(manifest.get("name") or "")
    if name != skill_dir.name:
        problems.append("skill.json name must equal the directory name")
    if not NAME_RE.fullmatch(name):
        problems.append("name must be lowercase-kebab")
    if not VERSION_RE.fullmatch(str(manifest.get("version") or "")):
        problems.append("version must be x.y.z")
    if not str(manifest.get("author") or "").strip():
        problems.append("author is required")
    entrypoint = skill_dir / str(manifest.get("entrypoint") or "")
    if not entrypoint.is_file():
        problems.append(f"missing entrypoint: {manifest.get('entrypoint')}")
    skill_doc_path = skill_dir / "SKILL.md"
    if skill_doc_path.is_file():
        if "--confirm" not in skill_doc_path.read_text(encoding="utf-8"):
            problems.append("SKILL.md must explain the --confirm rule")
    else:
        problems.append("missing SKILL.md")
    if entrypoint.is_file():
        source = entrypoint.read_text(encoding="utf-8")
        if re.search(r"https?://", source):
            problems.append("entrypoint must not hardcode a URL; use SAKURAMEDIA_BASE_URL")
        if re.search(r"\bsk-[A-Za-z0-9]", source):
            problems.append("entrypoint must not contain a literal API key")
        commands = _load_commands(source)
        if commands is None:
            problems.append("entrypoint must declare a COMMANDS literal")
        else:
            write_commands = [
                str(command.get("name"))
                for command in commands
                if isinstance(command, dict) and command.get("side_effect") == "write"
            ]
            if write_commands:
                if not re.search(r"""add_argument\(\s*["']--confirm["']""", source):
                    problems.append(
                        "write commands must register --confirm: "
                        + ", ".join(write_commands)
                    )
                if "args.confirm" not in source:
                    problems.append("write commands must check args.confirm")
    if problems:
        _emit({"ok": False, "problems": problems})
        return 1
    _emit({"ok": True, "skill_dir": str(skill_dir)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan and scaffold SakuraMedia agent skills"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    describe = subparsers.add_parser(
        "describe", help="List endpoints from the live backend or a saved schema"
    )
    describe.add_argument("--schema", type=Path, default=None)
    describe.add_argument("--filter", default=None)
    describe.add_argument("--method", default=None)
    describe.add_argument("--json", action="store_true")
    describe.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    describe.set_defaults(handler=cmd_describe)

    scaffold = subparsers.add_parser(
        "scaffold", help="Write a skill skeleton for chosen endpoints"
    )
    scaffold.add_argument("--name", required=True)
    scaffold.add_argument("--description", required=True)
    scaffold.add_argument("--display-name", default=None)
    scaffold.add_argument("--author", default="")
    scaffold.add_argument("--endpoint", action="append", default=[])
    scaffold.add_argument("--output", default=".")
    scaffold.add_argument("--schema", type=Path, default=None)
    scaffold.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    scaffold.add_argument("--force", action="store_true")
    scaffold.set_defaults(handler=cmd_scaffold)

    validate = subparsers.add_parser(
        "validate", help="Check a generated skill directory"
    )
    validate.add_argument("--skill-dir", required=True)
    validate.set_defaults(handler=cmd_validate)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except BuilderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
