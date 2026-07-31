---
name: au-task0
description: Convert and package dragged audio, generate jl_isd.fw with the strong-burn tool, then authorize it with AD15n. Invoke explicitly with /au-task0.
disable-model-invocation: true
---

# AU Task 0：转换、打包、强烧并授权

仅使用本套件的 MCP `au-task-workflow`，不要依赖外部 `audio-workflow`，
也不要改用 Shell 或自行操作GUI。

1. 从用户本次消息拖入或 `@` 附加的内容中收集本地音频文件、`processed`
   文件夹或其父目录。保持路径不变。
2. 如果没有明确输入路径，要求用户拖入文件/文件夹后再继续，不要使用
   当前工作区根目录代替。
3. 调用 `check_audio_environment`。本模式要求转换工具、pRFiles、
   packres.exe、new_packres.bat、test_dir、`强烧工具\download.bat`、
   `强烧工具\toy`、AD15n授权工具及授权KEY可用；缺失时列出路径并停止。
4. 调用：

```json
{
  "input_paths": ["用户拖入的路径"],
  "workflow_step": 2
}
```

使用 MCP 工具 `start_audio_workflow`。该模式会在转换前删除音频文件名中的
空白字符，输出 `converted`，然后依次：

1. 生成 `OUTPUT.LST` 和 `dir_music`；
2. 用新的 `dir_music` 替换 `强烧工具\toy\dir_music`，删除旧的
   `toy\jl_isd.fw`（不存在时忽略）；
3. 在 `强烧工具` 目录执行 `download.bat`，确认 `toy` 中生成新的
   `jl_isd.fw`；
4. 启动 `AD15n授权工具\固件文件烧写授权工具_1.5.4.exe`，选择上述
   `jl_isd.fw` 和 `26华钜芯-AD15N-9016-AA515221.lkey`，选择“无限制”
   并点击“授权”；
5. 检测新增或更新的 `.fw` 文件，确认授权成功。

5. 保存 `job_id`，使用 `get_audio_workflow_status` 持续查询直到
   `completed`、`failed` 或 `cancelled`。不要重复启动相同任务。
6. 查询期间报告阶段、百分比及 `current/total`。用户要求取消时调用
   `cancel_audio_workflow`。
7. 成功后明确列出 `converted`、`dir_music`、`jl_isd.fw` 和已授权
   `.fw`；失败时给出 `error` 与最后相关日志。
