---
name: au-task1
description: Convert dragged audio files with the configured AD140 converter without packaging. Invoke explicitly with /au-task1.
disable-model-invocation: true
---

# AU Task 1：仅转换

仅使用本套件的 MCP `au-task-workflow`，不要依赖外部 `audio-workflow`，
也不要改用 Shell 或自行操作GUI。

1. 收集用户本次消息拖入或 `@` 附加的音频文件、`processed` 文件夹或其
   父目录。没有明确路径时要求用户先提供，不要猜测。
2. 调用 `check_audio_environment`。本模式只要求杰理音频转换工具可用；
   FFmpeg、pRFiles或packres缺失不影响本模式。
3. 调用 MCP 工具 `start_audio_workflow`：

```json
{
  "input_paths": ["用户拖入的路径"],
  "workflow_step": 3
}
```

该模式会先删除输入音频文件名中的空白字符，再输出 `converted`，不会生成
`OUTPUT.LST` 或 `dir_music`。

4. 保存 `job_id`，使用 `get_audio_workflow_status` 持续查询至终态，不要
   重复启动任务。用户要求取消时调用 `cancel_audio_workflow`。
5. 成功后列出 `converted` 完整路径和结果数量；失败时给出 `error` 与
   最后相关日志。
