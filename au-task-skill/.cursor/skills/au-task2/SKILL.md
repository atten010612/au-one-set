---
name: au-task2
description: Package an existing converted folder, generate jl_isd.fw, and authorize it without converting audio. Invoke explicitly with /au-task2.
disable-model-invocation: true
---

# AU Task 2：从打包开始

仅使用本套件的 MCP `au-task-workflow`，不要依赖外部 `audio-workflow`，
也不要改用 Shell 或自行操作GUI。

1. 收集用户本次消息拖入或 `@` 附加的 `converted` 文件夹。也可以接受
   `processed` 文件夹或其父目录，由 MCP 定位同级 `converted`。
2. 原始 WAV/MP3 等音频不能直接执行本模式；没有 `converted` 时提示用户
   先运行 `/au-task1` 或 `/au-task0`。
3. 调用 `check_audio_environment`。本模式要求 pRFiles、packres.exe、
   new_packres.bat、test_dir、强烧工具、AD15n授权工具及KEY可用；转换
   工具或FFmpeg缺失不影响本模式。
4. 调用 MCP 工具 `start_audio_workflow`：

```json
{
  "input_paths": ["用户拖入的converted路径"],
  "workflow_step": 4
}
```

该模式会删除旧转换文件名中的空白字符，生成 `OUTPUT.LST`，复制资源到
`test_dir`，执行 `new_packres.bat` 并校验 `dir_music`，随后生成
`toy\jl_isd.fw` 并通过 AD15n 工具按“无限制”模式授权。

5. 保存 `job_id`，使用 `get_audio_workflow_status` 持续查询至终态。用户
   要求取消时调用 `cancel_audio_workflow`。
6. 成功后列出 `OUTPUT.LST`、`dir_music`、`jl_isd.fw` 和已授权 `.fw`
   完整路径；失败时给出 `error` 与最后相关日志。
