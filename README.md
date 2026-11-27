# SakuraMedia Plugin Market

[简体中文](./README.zh-CN.md) | English

Index repository for the SakuraMedia plugin market. SakuraMedia clients read this repository's [`index.json`](index.json) from "System Settings → Plugins → Plugin Market" to display the plugin list, download packages, and install or update plugins with one click.

- Default market source: `https://raw.githubusercontent.com/tinypinglite/sakuramedia-plugin-market/main/index.json`
- Plugins run inside the SakuraMedia backend process. Most official plugins are distributed as compiled artifacts through Releases in this repository; `sakuramedia_local_provider` is open source and publishes its packages in its own public repository, while this repository only indexes it. Community plugins point to release packages in their public repositories.

## Submitting a plugin

1. Fork this repository and add `plugins/<plugin_id>.json` (the filename must exactly match `plugin_id`):

   ```json
   {
     "plugin_id": "sakuramedia_example",
     "display_name": "Example Plugin",
     "description": "A one-sentence description of the plugin, up to 200 characters.",
     "author": "Your name",
     "repo": "your-name/your-plugin-repo",
     "homepage": "https://github.com/your-name/your-plugin-repo",
     "categories": ["other"],
     "official": false
   }
   ```

2. Do not hardcode the `latest` field for community plugins: the index maintenance workflow syncs the version, download URL, and SHA-256 from the repository's Releases (`source=external` every 30 minutes, a full verification once a day). Versions must use the three-part `x.y.z` format, and each Release must contain only one `.zip` plugin package (an optional `.sha256` file may be included). `source` can be omitted and defaults to `external`.
   - Release tags are read as `v<version>` by default. Repositories that host several plugins (such as the public monorepo `sakuramedia-open-plugins`) must use `<plugin_id>-v<version>`; the sync only picks the tags that belong to the plugin.
   - The sync also writes `releases/<plugin_id>.json` (with `tag_name` normalized to `v<version>`); a plugin can point `release_api_url` in its `manifest.json` at `https://tinypinglite.github.io/sakuramedia-plugin-market/releases/<plugin_id>.json` for client-side update checks.
3. Submit a Pull Request to this repository explaining the plugin's purpose and repository URL. Official plugins are written automatically by maintainers (closed-source ones through the release Action in a private monorepo, open-source ones from the public monorepo `sakuramedia-open-plugins`), and external PRs modifying them are not accepted.

Available categories: `storage` (storage / downloads), `metadata` (metadata), `discovery` (rankings / discovery), `automation` (automated tasks), `subtitle` (subtitles), and `other`.

See [`schema/plugin.schema.json`](schema/plugin.schema.json) for the complete field definitions.


## Skills

`skills/<name>/` holds the agent skill sources (`skill.json`, `SKILL.md`, entrypoint script), and the same directory holds the packaged `skills/<name>-<version>.zip` files plus `skills/index.json`. SakuraMedia clients read that index from "Connect Agent".

To add or update a skill:

1. edit or create `skills/<name>/` (`skill.json` name must equal the folder name; bump `version` for content changes),
2. run `python3 scripts/package_skills.py`,
3. commit the sources together with the regenerated zip and `index.json`.

`scripts/validate_metadata.py` fails the build when the packaged artifacts do not match the sources. The `sakuramedia-` name prefix and the `SakuraMedia` author name are reserved for official skills.

## Multilingual metadata

The **plugin manifest is the single source of truth** for multilingual plugin names and descriptions: a plugin declares `display_name_i18n` and `description` / `description_i18n` in `manifest.json`, and the index maintenance workflow copies them into `plugins/<plugin_id>.json` and `index.json` when syncing a Release.

- `display_name` / `description`: The original text (usually Chinese). If the manifest declares them, the manifest takes precedence; otherwise, the existing market copy is retained.
- `display_name_i18n` / `description_i18n`: Optional dictionaries whose keys are language tags (`zh-CN` / `en`). If declared in the manifest, they are synced as a whole; if not, the keys are removed.
- These four fields are written automatically by scripts. **Do not write them manually when submitting a plugin.** To change the copy, update the plugin manifest and publish a new version; the index will follow automatically.
- The client resolves values in the order "current language → `zh-CN` → original text." Plugins without multilingual copy still display their original text in the English UI.

## Manual installation

Without the plugin market, you can download most official plugin `.zip` files from this repository's Releases page, `sakuramedia_local_provider` from its own repository's Releases page, and community plugins from their public repositories' Releases pages, then upload them manually in "System Settings → Plugins." Restart the SakuraMedia container after installing or updating a plugin.

## Security notice

Plugins run inside the SakuraMedia backend process and have access to every capability exposed by the host. Only install plugins from trusted sources. Most official plugins are compiled artifacts, so their source cannot be audited directly; `sakuramedia_local_provider` publishes its source and can be audited. Community plugins are published as source and are not officially audited; review their source before installing.

## License

This project is licensed under the [PolyForm Noncommercial License 1.0.0](./LICENSE); non-commercial use only.

Copyright (C) 2026 tinypinglite
