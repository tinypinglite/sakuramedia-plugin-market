# SakuraMedia 插件市场

SakuraMedia 插件市场的索引仓库。SakuraMedia 客户端在「系统设置 → 插件 → 插件市场」读取本仓库的 [`index.json`](index.json)，展示插件列表、下载安装包并一键安装或更新。

- 默认市场源：`https://raw.githubusercontent.com/tinypinglite/sakuramedia-plugin-market/main/index.json`
- 插件在 SakuraMedia 后端进程内运行，只收录公开提供 Release 安装包的插件。

## 收录政策

- 收录**官方**与**社区**插件；官方插件标记 `official: true`，社区插件标记 `official: false`。
- 收录的插件仓库必须公开，Release 必须提供根目录含 `manifest.json` 的 `.zip` 安装包，且 `manifest.plugin_id` 与 `version` 和 Release tag 一致。
- 不收录私有仓库、来源不明或包含恶意行为的插件。

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

2. `latest` 字段不要手写：索引维护流程会每天自动从仓库的最新 Release 同步版本号、下载地址和 sha256。版本号必须是 `x.y.z` 三段格式，Release 里只放一个 `.zip` 插件包（可附带 `.sha256` 文件）。
3. 向本仓库提交 Pull Request，说明插件用途与仓库地址；官方插件由维护者直接提交。

分类可选值：`storage`（存储 / 下载）、`metadata`（元数据）、`discovery`（榜单 / 发现）、`automation`（自动化任务）、`subtitle`（字幕）、`other`。

字段完整定义见 [`schema/plugin.schema.json`](schema/plugin.schema.json)。

## 索引生成

`index.json` 由 [`scripts/build_index.py`](scripts/build_index.py) 生成：

```bash
GITHUB_TOKEN=xxx python3 scripts/build_index.py
```

脚本对 `plugins/` 下的每个插件：

1. 查询仓库的最新 Release；
2. 下载 `.zip` 包并读取其中的 `manifest.json`，校验 `plugin_id`、`version` 与 tag 一致；
3. 计算 sha256，回写插件元数据的 `latest` 字段；
4. 汇总所有插件重新生成 `index.json`。

任一插件失败时不写入任何文件，避免市场出现半截数据。客户端安装前会下载校验 sha256。

## 手动安装

不使用插件市场时，也可以从插件仓库的 Release 页面下载 `.zip`，在「系统设置 → 插件」手动上传安装。安装或更新后需要重启 SakuraMedia 容器。

## 安全提示

插件会在 SakuraMedia 后端进程内运行，拥有宿主开放的全部能力。请只安装可信来源的插件；社区插件未经官方审计，安装前建议先阅读其源码。
