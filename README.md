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

2. Do not hardcode the `latest` field for community plugins: the index maintenance workflow automatically syncs the version, download URL, and SHA-256 from the repository's latest Release every day. Versions must use the three-part `x.y.z` format, and each Release must contain only one `.zip` plugin package (an optional `.sha256` file may be included). `source` can be omitted and defaults to `external`.
3. Submit a Pull Request to this repository explaining the plugin's purpose and repository URL. Official plugins are written automatically by maintainers (most through the release Action in a private monorepo; `sakuramedia_local_provider` from its public source repository), and external PRs modifying them are not accepted.

Available categories: `storage` (storage / downloads), `metadata` (metadata), `discovery` (rankings / discovery), `automation` (automated tasks), `subtitle` (subtitles), and `other`.

See [`schema/plugin.schema.json`](schema/plugin.schema.json) for the complete field definitions.


## Skills

`skills/index.json` plus the packaged `skills/<name>-<version>.zip` archives serve the SakuraMedia agent skills (`App → Connect Agent`). **Do not edit this directory by hand**: it is written by the `Release Skills` workflow in [`tinypinglite/sakuramedia-official-plugins`](https://github.com/tinypinglite/sakuramedia-official-plugins), which packages `skills/**` on every push to `main` and validates the result with `scripts/validate_metadata.py`.

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
