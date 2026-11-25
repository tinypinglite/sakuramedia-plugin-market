# SakuraMedia 插件市场

简体中文 | [English](./README.md)

SakuraMedia 插件市场的索引仓库。SakuraMedia 客户端在「系统设置 → 插件 → 插件市场」读取本仓库的 [`index.json`](index.json)，展示插件列表、下载安装包并一键安装或更新。

- 默认市场源：`https://raw.githubusercontent.com/tinypinglite/sakuramedia-plugin-market/main/index.json`
- 插件在 SakuraMedia 后端进程内运行。多数官方插件以编译产物经本仓库 Release 分发；`sakuramedia_local_provider` 源码公开、安装包在其公开仓库 Release 中发布，本仓库只做索引。社区插件收录其公开仓库的 Release 安装包。


## 上架插件

1. Fork 本仓库，在 `plugins/` 下新增 `<plugin_id>.json`（文件名必须与 `plugin_id` 完全一致）：

   ```json
   {
     "plugin_id": "sakuramedia_example",
     "display_name": "示例插件",
     "description": "一句话说明插件用途，不超过 200 字。",
     "author": "你的名字",
     "repo": "your-name/your-plugin-repo",
     "homepage": "https://github.com/your-name/your-plugin-repo",
     "categories": ["other"],
     "official": false
   }
   ```

2. 社区插件的 `latest` 字段不要手写：索引维护流程会每天自动从仓库的最新 Release 同步版本号、下载地址和 sha256。版本号必须是 `x.y.z` 三段格式，Release 里只放一个 `.zip` 插件包（可附带 `.sha256` 文件）。`source` 可省略，缺省按 `external` 处理。
3. 向本仓库提交 Pull Request，说明插件用途与仓库地址；官方插件由维护者自动写入（多数来自私有 monorepo 的发版 Action，`sakuramedia_local_provider` 来自其公开源码仓），不接受外部 PR 修改。

分类可选值：`storage`（存储 / 下载）、`metadata`（元数据）、`discovery`（榜单 / 发现）、`automation`（自动化任务）、`subtitle`（字幕）、`other`。

字段完整定义见 [`schema/plugin.schema.json`](schema/plugin.schema.json)。


## Skills

`skills/index.json` 和打包好的 `skills/<name>-<version>.zip` 是给 SakuraMedia 的 Agent skill 用的（客户端「连接 Agent」页面读取）。**这个目录不要手改**：它由 [`tinypinglite/sakuramedia-official-plugins`](https://github.com/tinypinglite/sakuramedia-official-plugins) 的 `Release Skills` workflow 在每次 push `main` 时打包写入，并由 `scripts/validate_metadata.py` 校验。

## 多语言元数据

插件名称与简介的多语言文案以**插件 manifest 为唯一事实源**：插件在 `manifest.json` 里声明
`display_name_i18n` 与 `description` / `description_i18n`，索引维护流程在同步 Release 时把它们搬进
`plugins/<plugin_id>.json` 与 `index.json`。

- `display_name` / `description`：原文（通常是中文）。manifest 声明了就以 manifest 为准，没声明就保留市场里已有的文案。
- `display_name_i18n` / `description_i18n`：可选字典，键为语言标签（`zh-CN` / `en`）。manifest 声明了就整块同步，没声明就删掉该键。
- 这四个字段由脚本自动写入，**投稿时不要手写**；要改文案就改插件 manifest 并发一版，索引会自动跟上。
- 客户端按「当前语言 → `zh-CN` → 原文」的顺序取值；没有多语言文案的插件在英文界面下仍显示原文。

## 手动安装

不使用插件市场时，多数官方插件可从本仓库的 Release 页面下载 `.zip`，`sakuramedia_local_provider` 从其公开仓库的 Release 页面下载，社区插件从其公开仓库的 Release 页面下载，然后在「系统设置 → 插件」手动上传安装。安装或更新后需要重启 SakuraMedia 容器。

## 安全提示

插件会在 SakuraMedia 后端进程内运行，拥有宿主开放的全部能力。请只安装可信来源的插件；多数官方插件是编译产物，无法直接审计源码，`sakuramedia_local_provider` 的源码公开可审计；社区插件以源码发布且未经官方审计，安装前建议先阅读其源码。
## License

本项目采用 [PolyForm Noncommercial License 1.0.0](./LICENSE)，仅允许非商业用途。

Copyright (C) 2026 tinypinglite
