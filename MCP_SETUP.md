# Cursor MCP 安装与软件放置

本 MCP 运行在本地 Windows Cursor 桌面会话中。不要从 WSL、SSH、
Dev Container 或锁屏会话启动，因为杰理工具需要可交互桌面。

## 1. 建立完整目录

下载代码后保持以下结构：

```text
audio-workflow\
├── .cursor\
│   └── mcp.json
├── audio_processor.py
├── converter_automation.py
├── packer_automation.py
├── mcp_server.py
├── audio_processor_config.json
├── requirements-mcp.txt
├── setup_mcp.bat
├── tools\
│   ├── ffmpeg.exe（可选）
│   └── ffprobe.exe（可选）
└── au-task-skill\（也可以放在其他固定位置）
    └── vendor\
        ├── converter\
        │   ├── 音频文件转换工具_1.2.2.exe
        │   └── 该软件原有的其他文件和子目录
        ├── ad140\
            ├── packres\
            │   ├── pRFiles.exe
            │   └── pRFiles原有的其他文件和子目录
            └── test_dir\
                ├── packres.exe
                └── new_packres.bat
        ├── 强烧工具\
        │   ├── download.bat
        │   └── toy\
        └── AD15n授权工具\
            ├── 固件文件烧写授权工具_1.5.4.exe
            └── 26华钜芯-AD15N-9016-AA515221.lkey
```

不要把工具原文件夹再套一层。例如以下路径是错误的：

```text
au-task-skill\vendor\converter\音频转换工具文件夹\音频文件转换工具_1.2.2.exe
```

EXE 必须直接位于上图指定的位置。运行
`au-task-skill\install_global_skills.bat` 会设置
`AU_TASK_SKILL_HOME` 环境变量。移动 Skill 文件夹后需要重新运行安装器并
Reload Cursor。

`new_packres.bat` 必须删除 `pause`，推荐内容：

```bat
@echo off
cd /d "%~dp0"
packres.exe -n test_dir -list OUTPUT.LST -o dir_music -normal
exit /b %errorlevel%
```

生成 `dir_music` 后，MCP 会覆盖 `强烧工具\toy\dir_music`，删除旧
`jl_isd.fw` 并从 `强烧工具` 目录执行 `download.bat`。随后会将新生成的
`toy\jl_isd.fw` 和上图的 `.lkey` 载入 AD15n 授权工具，选择“无限制”并
授权。

## 2. 安装 MCP Python 环境

电脑需要 Python 3.10 或更高版本。双击：

```text
setup_mcp.bat
```

它会建立项目内的 `.venv`，并安装固定版本：

```text
fastmcp 3.4.4
pywinauto 0.6.9
```

安装结束后在 Cursor 执行 “Developer: Reload Window”。

如果 FFmpeg 已经通过 winget、Chocolatey 或手工命令加入系统 PATH，
不需要再复制到 `tools`。环境检查会依次接受项目内 `tools` 或系统
PATH。FFmpeg 刚安装后必须重启 Cursor，让 MCP 继承最新 PATH。

安装 BAT 使用纯 ASCII 输出，避免 Windows CMD 将 UTF-8 中文行错误解析为
命令。也可以手动检查：

```bat
.venv\Scripts\python.exe mcp_server.py --check
```

## 3. Cursor MCP 工具

项目级配置已经位于 `.cursor\mcp.json`。MCP 名称为
`audio-workflow`，提供：

```text
start_audio_workflow
get_audio_workflow_status
cancel_audio_workflow
list_audio_workflows
check_audio_environment
```

启动示例：

```json
{
  "input_paths": ["D:\\语音项目"],
  "workflow_step": 0
}
```

流程值：

```text
0：音频处理 → 转换 → 合成
1：仅音频处理
2：转换 → 合成
3：仅转换
4：仅合成
```

`start_audio_workflow` 会立即返回 `job_id`。使用
`get_audio_workflow_status` 查询阶段、百分比、文件数量、日志和产物。

## 4. 排队与取消

杰理 GUI 工具不能安全地并行操作，因此音频任务一次只运行一个，后续
任务处于 `queued`。这不会阻塞 Cursor 的聊天、编辑或其他 MCP。

`cancel_audio_workflow` 会：

1. 将排队任务标记为取消；或
2. 终止运行中的工作进程及其启动的 GUI 子进程。

取消时尚未写完的单个输出可能需要人工删除。

## 5. Cursor斜杠命令

项目包含：

```text
.cursor\commands\音频处理0.md
.cursor\commands\音频处理1.md
.cursor\commands\音频处理2.md
.cursor\commands\音频处理3.md
.cursor\commands\音频处理4.md
```

重新加载 Cursor 后可以在 Agent 对话中使用：

```text
/音频处理0 @语音文件夹
/音频处理1 @input.wav
/音频处理2 @processed
/音频处理3 @processed
/音频处理4 @converted
```

没有 `@` 附加路径时，命令会让 MCP 使用项目根目录。命令会自动进行环境
检查、启动正确模式、轮询进度并汇报产物，不需要手动调用5个MCP工具。

Cursor 当前文档没有正式保证所有版本都支持中文命令名。如果命令列表中
没有显示中文名称，可以直接从 `.cursor\commands` 打开对应 Markdown，
或者复制为ASCII文件名，例如：

```text
audio-process-0.md → /audio-process-0
```

## 6. 相对路径与换电脑

`audio_processor_config.json` 使用 Skill目录环境变量：

```json
{
  "converter_path": "%AU_TASK_SKILL_HOME%\\vendor\\converter\\音频文件转换工具_1.2.2.exe",
  "packer_path": "%AU_TASK_SKILL_HOME%\\vendor\\ad140\\packres\\pRFiles.exe",
  "packres_input_directory": "%AU_TASK_SKILL_HOME%\\vendor\\ad140\\test_dir"
}
```

`install_global_skills.bat` 会把 `AU_TASK_SKILL_HOME` 设置为 Skill仓库
绝对路径。复制到另一台 Windows 电脑后，重新运行该安装器即可，不需要
修改 C盘/D盘路径。

若工具没有放在项目内，也可以把对应字段改为绝对路径。

## 7. 运行前检查

让 Cursor 调用：

```text
check_audio_environment
```

只有 `ready: true` 时再启动完整流程。缺失文件会在 `missing` 中列出。
