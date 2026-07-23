# Windows 语音批处理工具

这是一个可以直接投入使用的 FFmpeg 批处理脚本，适用于短促的纯人声提示音。它会：

1. 降低稳定底噪；
2. 只裁剪开头和结尾的静音，保留中间停顿；
3. 将每个文件分别归一化到统一响度；
4. 保留扩展名、采样率、声道数，并尽量保留原码率；
5. 不修改源文件，结果写入 `processed` 文件夹。

支持 WAV、MP3、M4A、AAC、FLAC、OGG、OPUS 和 WMA。脚本只使用 Python 标准库，不需要安装 Python 第三方包。

## Windows 快速使用

### 准备环境

需要 Windows 10/11 和 Python 3.10 或更高版本。

FFmpeg 可以采用以下任一方式：

- 把 `ffmpeg.exe` 和 `ffprobe.exe` 放入本项目的 `tools` 文件夹；
- 将 FFmpeg 加入系统 `PATH`；
- 让脚本通过 `winget` 自动安装。

自动安装命令：

```powershell
py -3 audio_processor.py --install-ffmpeg
```

首次运行且没有找到 FFmpeg 时，脚本也会询问是否通过 `winget` 安装。安装后如果仍提示找不到 FFmpeg，请关闭窗口并重新运行。

如果 Windows 的应用执行别名被安全策略拦截，可以先在 CMD 中手动安装：

```bat
winget install -e --id Gyan.FFmpeg --source winget
```

安装结束后关闭并重新打开 CMD，再运行脚本。也可以下载 Windows 版 FFmpeg，将 `ffmpeg.exe` 和 `ffprobe.exe` 放入脚本旁边的 `tools` 文件夹，完全绕过系统安装。

### 拖拽处理

将以下任一种内容拖到 `处理音频.bat`：

- 一个或多个音频文件；
- 一个文件夹；
- 多个文件和文件夹的组合。

双击 `处理音频.bat` 则扫描工具所在文件夹。处理结果位于每个源文件所在目录的 `processed` 文件夹。

### 命令行处理

处理当前文件夹：

```powershell
py -3 audio_processor.py
```

处理指定文件夹：

```powershell
py -3 audio_processor.py "D:\按摩仪提示音"
```

处理多个文件并指定输出目录：

```powershell
py -3 audio_processor.py "D:\a.wav" "D:\b.mp3" --output "D:\处理完成"
```

递归扫描子文件夹：

```powershell
py -3 audio_processor.py "D:\提示音" --recursive
```

## 文件已经完成部分处理时

不要依靠程序“猜测”音频是否已经降噪。成品波形无法可靠证明降噪是否做过，重复降噪可能产生金属音。

在脚本旁边建立 `processing-plan.csv`：

```csv
file,completed_steps
已经降噪.wav,denoise
已经降噪和裁剪.mp3,denoise|trim
已经全部处理.m4a,all
尚未处理.flac,none
```

可使用仓库中的 `processing-plan.example.csv` 作为模板：

```powershell
copy processing-plan.example.csv processing-plan.csv
```

步骤名称：

| 名称 | 含义 |
| --- | --- |
| `denoise` | 已降噪 |
| `trim` | 已裁剪头尾 |
| `normalize` | 已归一化 |
| `all` | 三项全部完成，原样复制 |
| `none` | 尚未处理 |

步骤之间使用 `|` 分隔。`file` 可以填写文件名或绝对路径；存在同名文件时应填写绝对路径。脚本会自动读取同目录下的 `processing-plan.csv`，也可以明确指定：

```powershell
py -3 audio_processor.py "D:\提示音" --completed-plan "D:\processing-plan.csv"
```

如果降噪或裁剪仍需执行，脚本会重新测量响度，因为前面的处理可能改变原有响度。

### 整批跳过某一步

```powershell
py -3 audio_processor.py "D:\提示音" --no-denoise
py -3 audio_processor.py "D:\提示音" --no-trim
py -3 audio_processor.py "D:\提示音" --no-normalize
```

这些参数可以组合。

## 防止重复处理

每个输出目录会生成 `processing-report.json`，记录：

- 源文件 SHA-256；
- 处理参数；
- 已应用步骤；
- 处理前后时长；
- 实测响度；
- 成功或失败状态。

使用相同参数再次运行时，只要源文件和成功输出都没有改变，脚本就会跳过该文件。修改参数后会生成新输出，不会把旧成品再次作为输入。递归扫描时也会忽略名为 `processed` 的目录。

已有同名输出且没有匹配的报告时，程序使用 `_1`、`_2` 等后缀，除非传入 `--overwrite`。

## 默认参数

| 参数 | 默认值 |
| --- | ---: |
| 并发任务 | 4 |
| 降噪量 | 12 dB |
| 估计底噪 | -50 dBFS |
| 静音阈值 | -45 dBFS |
| 最短静音检测时长 | 0.02 秒 |
| 头部最多保留 | 0.15 秒 |
| 结尾最多保留 | 0 秒 |
| 目标综合响度 | -16 LUFS |
| 真峰值上限 | -1.5 dBTP |
| 响度容差 | ±0.5 LU |

按摩仪器的实际扬声器可能产生明显染色。建议先选择数条提示音，在真机上试听默认的 `-16 LUFS`；如果声音过于激进，可改为：

```powershell
py -3 audio_processor.py "D:\提示音" --target-lufs -18
```

查看所有可调参数：

```powershell
py -3 audio_processor.py --help
```

头部裁剪采用“只减不增”规则：实际保留时长为
`min(原有头部静音, --keep-head-silence)`。例如原文件头部只有 0.05 秒，
即使头部上限是 0.15 秒，输出仍保留 0.05 秒，不会补足到 0.15 秒；
原头部为 0.30 秒时才会裁到 0.15 秒。

结尾处理更严格，`--keep-tail-silence` 默认为 `0`，检测到结尾静音后会
直接截到静音起点。需要保留少量尾巴时可以明确设置，例如：

```powershell
py -3 audio_processor.py "D:\提示音" --keep-tail-silence 0.03
```

中间停顿不受头尾规则影响。

## 输出和退出代码

处理某个文件失败不会中止其他文件。结束时会显示完成、复制、跳过和失败数量。

- `0`：全部成功；
- `1`：没有找到音频文件；
- `2`：至少一个文件失败。

MP3、AAC、OGG 等有损格式在处理后必须重新编码，因此无法做到比特级无损。程序使用无损 FLAC 中间文件，最终只进行一次有损编码。