---
name: au-task0
description: Convert dragged audio files with the configured AD140 converter, then package them into OUTPUT.LST and dir_music. Invoke explicitly with /au-task0.
disable-model-invocation: true
---

# AU Task 0：转换并打包

仅使用本套件的 MCP `au-task-workflow`，不要依赖外部 `audio-workflow`，
也不要改用 Shell 或自行操作GUI。

1. 从用户本次消息拖入或 `@` 附加的内容中收集本地音频文件、`processed`
   文件夹或其父目录。保持路径不变。
2. 如果没有明确输入路径，要求用户拖入文件/文件夹后再继续，不要使用
   当前工作区根目录代替。
3. 调用 `check_audio_environment`。本模式要求转换工具、pRFiles、
   packres.exe、new_packres.bat和test_dir可用；缺失时列出路径并停止。
4. 调用：

```json
{
  "input_paths": ["用户拖入的路径"],
  "workflow_step": 2
}
```

使用 MCP 工具 `start_audio_workflow`。该模式会在转换前删除音频文件名中的
空白字符，输出 `converted`，然后生成 `OUTPUT.LST` 和 `dir_music`。

5. 保存 `job_id`，使用 `get_audio_workflow_status` 持续查询直到
   `completed`、`failed` 或 `cancelled`。不要重复启动相同任务。
6. 查询期间报告阶段、百分比及 `current/total`。用户要求取消时调用
   `cancel_audio_workflow`。
7. 成功后明确列出 `converted` 和 `dir_music`；失败时给出 `error` 与
   最后相关日志。
