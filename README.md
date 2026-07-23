# Windows 语音批处理工具

这是一个可以直接投入使用的 FFmpeg 批处理脚本，适用于短促的纯人声提示音。它会：

1. 降低稳定底噪；
2. 只裁剪开头和结尾的静音，保留中间停顿；
3. 将每个文件分别归一化到统一响度；
4. 保留扩展名、采样率、声道数，并尽量保留原码率；
5. 不修改源文件，结果写入 `processed` 文件夹。

支持 WAV、MP3、M4A、AAC、FLAC、OGG、OPUS 和 WMA。基础音频处理只使用
Python 标准库；启用专用转换工具自动操作时，脚本会安装
`pywinauto 0.6.9`。

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

双击 `处理音频.bat` 会递归扫描工具所在目录。可以把语音文件直接放在
脚本旁，也可以把整个语音文件夹放在脚本旁，不需要拖拽。处理结果位于
每个源文件所在目录的 `processed` 文件夹；程序会忽略已有的
`processed` 和 `converted` 目录，避免重复处理成品。

启动后首先选择本次流程：

```text
0 - 音频处理 → 转换 → 合成
1 - 只做音频处理
2 - 转换 → 合成
3 - 只做转换
4 - 只做合成
```

模式 2/3 会优先查找现有 `processed` 文件夹；没有 `processed` 时才读取
指定目录中的音频。模式 4 直接读取 `converted`，不会检查 FFmpeg。
传入的目录本身是 `processed` 或 `converted` 也能正确识别其同级关系。

音频处理成功后，如果脚本旁存在启用的 `audio_processor_config.json`，
程序会继续打开“音频文件转换工具 1.2.2”，自动添加刚处理好的文件、
选择格式/采样率/码率、填写保存目录并点击“开始转换”。

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

无人值守运行时可以跳过询问：

```powershell
py -3 audio_processor.py --workflow-step 0
py -3 audio_processor.py "D:\提示音" --workflow-step 1
py -3 audio_processor.py "D:\提示音\processed" --workflow-step 2
py -3 audio_processor.py "D:\提示音\processed" --workflow-step 3
py -3 audio_processor.py "D:\提示音\converted" --workflow-step 4
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

脚本会在降噪之前记录原文件的头部时长，并在降噪后恢复相同的头部边界。
这会抵消 `afftdn` 滤镜可能产生的约 0.025 秒处理延迟，避免处理后的头部
比原文件更长。

结尾处理更严格，`--keep-tail-silence` 默认为 `0`，检测到结尾静音后会
直接截到静音起点。需要保留少量尾巴时可以明确设置，例如：

```powershell
py -3 audio_processor.py "D:\提示音" --keep-tail-silence 0.03
```

中间停顿不受头尾规则影响。

## 专用音频转换工具

默认配置文件是脚本旁的 `audio_processor_config.json`：

```json
{
  "enabled": true,
  "converter_path": "D:\\soft\\语音烧录\\杰理音频转换工具\\AD140音频转换工具\\media_convert_tools\\convert_to_.f1a.f1b.ump3.a.b.e\\音频文件转换工具_1.2.2.exe",
  "format": "F1A",
  "sample_rate": "32K",
  "bit_rate": "32K",
  "output_folder_name": "converted",
  "auto_install_pywinauto": true,
  "clear_existing_files": true,
  "window_title_regex": ".*音频文件转换工具.*",
  "startup_timeout_seconds": 20,
  "conversion_timeout_seconds": 120,
  "packer_enabled": true,
  "packer_path": "D:\\soft\\语音烧录\\杰理音频转换工具\\AD140打包工具\\packres\\pRFiles.exe",
  "packer_window_title_regex": ".*调整文件顺序.*",
  "packer_output_name": "OUTPUT.LST",
  "packer_timeout_seconds": 30,
  "packres_batch_name": "new_packres.bat",
  "packres_output_name": "dir_music",
  "packres_timeout_seconds": 60
}
```

默认自动选择截图所示的 `F1A / 32K采样率 / 32K码率`，然后点击
“开始转换”。可以填写的选项为：

- 格式：`A`、`E`、`F1A`、`F1C`、`UMP3`
- 采样率：`8K`、`12K`、`16K`、`24K`、`32K`
- 码率：`8K`、`16K`、`24K`、`32K`、`40K`、`48K`、`56K`、`64K`

### 换到其他电脑

在新电脑上打开脚本旁的：

```text
audio_processor_config.json
```

修改其中的 `converter_path`。JSON 中的 Windows 路径必须使用双反斜杠，
例如：

```json
{
  "converter_path": "C:\\Tools\\音频文件转换工具_1.2.2.exe"
}
```

如果保存的路径不存在，运行时会弹出文件选择窗口。选择新电脑上的
`音频文件转换工具_1.2.2.exe` 后，脚本会自动把新路径写回配置文件。

### 转换保存目录

- 拖入一个文件夹：在该文件夹内建立 `converted`；
- 拖入单个文件或多个文件：在脚本所在目录建立 `converted`；
- 双击 BAT 扫描当前目录：在当前目录建立 `converted`。

转换工具的控件结构如果与 1.2.2 版本不同，自动操作会停止，并在
`converted\converter-controls.txt` 保存识别到的控件信息。它不会使用
固定屏幕坐标，因此正常情况下不受窗口位置和分辨率影响。

部分 1.2.2 版本点击“添加文件”后，文件选择窗口仍使用转换工具本身的
标题，而不是“打开”。脚本通过新窗口句柄识别此窗口；如果窗口没有暴露
“文件名”控件，脚本会切换到 Win32 后端，通过系统固定控件编号 `1148`
直接填写文件路径，不会把文件名输入右上角的“搜索”框。

大量文件不会一次性写入旧版文件窗口。脚本按最多 8 个文件、最多 3000
字符分批添加；每一批必须确认“文件名”控件已经关闭后才打开下一批。
这避免四十多个完整路径超过对话框容量后只导入部分文件或出现“没有与
搜索条件匹配的项”。转换等待时间还会按每个文件至少 5 秒自动增长。

如果本轮所有结果都位于同一个 `processed`，并且其中不存在额外旧音频，
脚本会优先在文件窗口进入该目录，聚焦 `ItemsView`，执行 `Ctrl+A` 全选
并打开，效果与手工全选一致。`ItemsView` 不可用时依次尝试
`SysListView32`，最后在文件内容区域执行一次真实鼠标点击后再按
`Ctrl+A`。只有目录不满足安全条件或三种聚焦方式全部失败时，才回退到
上述每批 8 个文件的精确导入方式。

文件提交后，脚本以主界面转换列表的行数增加作为成功标志，不等待窗口
标题消失。按钮名称在部分版本中带有换行，匹配时会自动忽略空白字符。

转换工具的“保存目录”输入框不接受 UIA `SetValue`，会返回
`0x80131509 InvalidOperationException`。脚本优先通过原生 `WM_SETTEXT`
设置并读取校验，必要时才使用 Unicode 剪贴板。格式、采样率和码率通过
UIA SelectionItem 模式选择，并读取 `is_selected` 校验，不使用受 DPI
缩放影响的屏幕坐标。

如果该版本同时忽略 `WM_SETTEXT` 和键盘粘贴，脚本会点击界面右侧的
“打开”，在系统文件夹选择器中导航到 `converted`，点击“选择文件夹”
或“确定”，再回读主界面的目录。这样会同时更新软件内部状态，避免虽然
输入框看似操作过、开始转换时却提示“请选择输出文件位置”。

点击“开始转换”后，脚本会监测错误弹窗，并等待保存目录出现与输入文件
数量相同的新文件或更新文件。默认等待上限为 120 秒；没有实际结果时
返回错误代码 3，不再仅凭点击成功就报告完成。

校验时会先统计实际输出，再处理弹窗。“转换完成/成功”等提示会自动点击
“确定”并继续校验；只有包含“错误、失败、请选择、没有匹配项”等内容的
窗口才立即判定失败。等待期间每 10 秒显示一次
`已发现 X/Y 个结果`，超时时报告实际数量和最后一条提示。

`已发现 X/Y` 现在按输入与输出的文件主名匹配统计，而不是只统计本轮
时间戳变化。例如目录原有17个结果、本轮新增26个时，会识别为43/43；
但必须至少有一个本轮变化，或收到转换完成提示，才会接受已有文件，
避免仅凭陈旧结果误报成功。

## OUTPUT.LST 音频文件合成

专用格式转换并校验成功后，脚本会继续：

1. 打开 `packer_path` 指定的 `pRFiles.exe`；
2. 根据 `converted` 的绝对路径选择对应磁盘；
3. 在右侧树形目录逐层展开每一级文件夹；
4. 选中 `converted`，文件顺序保持工具加载结果；
5. 点击“保存”；
6. 校验 `pRFiles.exe` 同级目录中的 `OUTPUT.LST` 已生成或更新；
7. 将 `converted` 中的 `.a/.e/.f1a/.f1b/.f1c/.ump3` 文件复制到
   `pRFiles.exe` 同级目录；
8. 执行同级的 `new_packres.bat`；
9. 校验同级 `dir_music` 已生成或更新并显示“输出成功”。

换到其他电脑时，在同一个 `audio_processor_config.json` 中修改：

```json
{
  "packer_path": "C:\\实际目录\\packres\\pRFiles.exe"
}
```

路径无效时会弹窗选择 `pRFiles.exe` 并保存新路径。临时关闭合成功能可将
`packer_enabled` 改为 `false`。打包操作失败时，控件信息会写到
`pRFiles.exe` 同级的 `packer-controls.txt`。

该工具是 32 位 Delphi 程序，可能显示“32-bit application should be
automated using 32-bit Python”警告；这不是失败。脚本使用其实际控件
`TDriveComboBox`、`TDirectoryListBox` 和 `TBitBtn`，并通过原生窗口
消息操作，不需要另外安装 32 位 Python。左上方显示的绝对路径是
`OUTPUT.LST` 输出路径，不代表右侧目录列表的当前状态，因此脚本每次
都会先找到并双击磁盘根节点（例如 `D:\`），退出之前展开的 `project`
等其他分支；随后动态等待真实路径的每一级目录出现。选中每一级目录后
发送原生 `LBN_DBLCLK` 通知，等价于手工双击进入，最后确认左侧源文件
列表已经加载。目录名来自实际 `converted` 绝对路径，不依赖
`au-one-set` 这个固定名称。

“保存”按钮会打开模态“另存为”窗口。脚本使用异步 `BM_CLICK`，避免
同步按钮消息卡死；随后在文件名框填写
`pRFiles.exe同级目录\OUTPUT.LST`，按回车保存，并自动确认覆盖已有文件。
只有 `OUTPUT.LST` 实际新建或更新时间发生变化才算合成成功。

文件名查找同时支持新版文件窗口编号 1148、旧式 Win32 `edt1` 编号
1152，以及 `ComboBoxEx32/ComboBox` 内嵌 Edit。仍无法识别时会在
`pRFiles.exe` 同级生成 `packer-save-as-controls.txt`，其中只记录
“另存为”窗口，便于继续适配。

另一些 `pRFiles.exe` 构建不会弹出另存为，而是直接更新同级的固定文件
`LIST.LST`。脚本会监测其签名变化并复制为 `OUTPUT.LST`。若
`LIST.LST/OUTPUT.LST` 都没有变化且两个自动化后端都未发现新窗口，也会
生成 `packer-save-as-controls.txt`，列出当时所有可见窗口。

`new_packres.bat` 通过 `cmd.exe /d /c call` 在 `packres` 目录中执行，
默认超时60秒。退出码非0或 `dir_music` 没有实际更新都会判定第4部分
失败；日志、JSON 等非转换格式文件不会复制到打包工具目录。

第一次安装 `pywinauto` 时，脚本会立即刷新 `pywin32` 的模块路径。如果
Windows 仍提示 `No module named 'win32api'`，说明当前 Python 进程没有
加载新安装的 `.pth` 文件；关闭窗口后重新运行 BAT 即可，无需重复安装。

临时不运行转换工具：

```powershell
py -3 audio_processor.py "D:\提示音" --no-converter
```

使用另一份配置：

```powershell
py -3 audio_processor.py "D:\提示音" --converter-config "D:\converter-config.json"
```

## 输出和退出代码

处理某个文件失败不会中止其他文件。结束时会显示完成、复制、跳过和失败数量。

- `0`：全部成功；
- `1`：没有找到音频文件；
- `2`：至少一个文件失败。
- `3`：音频处理成功，但专用转换工具自动操作失败。

MP3、AAC、OGG 等有损格式在处理后必须重新编码，因此无法做到比特级无损。程序使用无损 FLAC 中间文件，最终只进行一次有损编码。