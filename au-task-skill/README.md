# AU Task Cursor Skills

这是一个可独立发布的 Cursor Skills 项目，仅提供杰理音频转换和打包入口。
实际执行由已经全局安装的 `audio-workflow` MCP 完成，不复制GUI自动化
代码。杰理软件统一放在本 Skill 仓库的 `vendor` 中。

## 软件目录

将之前建立的整个 `vendor` 文件夹移动到本仓库，最终必须是：

```text
au-task-skill\
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

Cursor 中必须已经全局配置并连接：

```text
audio-workflow
```

可让 Cursor 调用：

```text
check_audio_environment
```

确认所需工具存在。此 Skills 仓库本身不包含 FFmpeg或杰理软件。

## 全局安装

双击：

```text
install_global_skills.bat
```

它会复制到：

```text
%USERPROFILE%\.cursor\skills\au-task0
%USERPROFILE%\.cursor\skills\au-task1
%USERPROFILE%\.cursor\skills\au-task2
```

安装器还会设置当前 Windows 用户环境变量：

```text
AU_TASK_SKILL_HOME=本au-task-skill目录的绝对路径
```

全局 `audio-workflow` MCP 通过这个变量调用本仓库内的 EXE。移动本仓库
后必须重新运行安装器并 Reload Cursor。

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
