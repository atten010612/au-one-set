# AU Task Cursor Skills

这是一个可独立发布的 Cursor Skills + MCP 套件，只提供杰理音频转换和
打包功能。GUI自动化、任务队列、进度、取消和环境检查均位于本仓库的
`runtime`，不再依赖外部 `audio-workflow` 工程。

## 软件目录

将之前建立的整个 `vendor` 文件夹移动到本仓库，最终必须是：

```text
au-task-skill\
├── .cursor\skills\
├── runtime\
│   ├── au_task.py
│   ├── mcp_server.py
│   ├── converter_runtime.py
│   └── packer_runtime.py
├── audio_processor_config.json
├── requirements.txt
├── install_cursor.py
├── install_global_skills.bat
└── vendor\
    ├── converter\
    │   ├── 音频文件转换工具_1.2.2.exe
    │   └── 转换工具原有依赖
    └── ad140\
        ├── packres\
        │   ├── pRFiles.exe
        │   └── pRFiles原有依赖
        └── test_dir\
            ├── packres.exe
            └── new_packres.bat
```

不要保留旧工程根目录下的 `vendor`，也不要在上述路径中再套一层原文件夹。

## 命令

| 命令 | 功能 | MCP模式 |
| --- | --- | ---: |
| `/au-task0` | 去除文件名空白 → 转换 → 打包 | 2 |
| `/au-task1` | 去除文件名空白 → 仅转换，输出 `converted` | 3 |
| `/au-task2` | 仅打包，输出 `OUTPUT.LST` 和 `dir_music` | 4 |

## 前置条件

电脑只需安装 Python 3.10或更高版本，并按上方结构放好杰理工具。安装
完成后 Cursor 中会出现独立 MCP：

```text
au-task-workflow
```

可调用 `check_audio_environment` 验证。转换和打包不使用 FFmpeg。

## 全局安装

双击：

```text
install_global_skills.bat
```

安装器会：

```text
1. 在本仓库建立 .venv
2. 安装 FastMCP 和 pywinauto
3. 将三个 Skill 复制到 %USERPROFILE%\.cursor\skills
4. 安全合并 %USERPROFILE%\.cursor\mcp.json
5. 注册 au-task-workflow MCP
```

现有全局 MCP 配置会保留，并在修改前备份为 `mcp.json.backup`。移动本
仓库后必须重新运行安装器，让全局MCP指向新位置。

然后在 Cursor 中执行：

```text
Ctrl+Shift+P
Developer: Reload Window
```

卸载时运行 `uninstall_global_skills.bat`。

## 使用

将文件或文件夹拖入 Cursor Agent 对话框，并在同一条消息输入：

```text
/au-task0
```

也可以使用 `@`：

```text
/au-task0 @processed
/au-task1 @语音文件夹
/au-task2 @converted
```

Skill 会检查环境、调用正确的 MCP 模式、轮询进度、支持取消并汇报产物。
没有拖入或 `@` 指定路径时会要求用户补充，不会误处理当前工作区。

## 作为独立Git仓库

当前目录内容可以直接作为新仓库根目录：

```bat
cd au-task-skill
git init
git add .
git commit -m "Initial AU Task Cursor skills"
```

然后在 GitHub/GitLab 新建空仓库并添加远端。不要把外层音频处理工程一起
提交到这个 Skill 仓库。
