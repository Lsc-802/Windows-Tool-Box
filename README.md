# Windows Tool Box 测试版 v0.1

融合火绒式工具 + 系统实时检测的模块化 Windows 工具箱。当前完成**第一步**：硬件型号检测 + 系统资源实时检测。

## 项目结构

```
G:\Windows tool box\
├─ main.py                     # 程序入口（主框架：注册并调度模块 + 单实例保护）
├─ self_test.py                # 数据层自检脚本（不开界面）
├─ ui_smoke_test.py            # 界面冒烟测试（自动开窗渲染 3 秒后关闭）
├─ make_icon.py                # 生成应用图标 icon.ico
├─ build.bat                   # 【一键打包】编译成单文件 exe
├─ icon.ico                    # 应用图标
├─ dist\WindowsToolBox.exe     # 打包产物（即开即用的单文件 exe）
├─ requirements.txt            # 依赖清单
├─ 启动测试版.bat               # 双击启动仪表盘（会闪一下命令窗口）
├─ 启动测试版.vbs               # 【推荐】双击启动，零窗口闪现，无命令行残留
├─ 运行自检.bat                 # 双击运行自检
├─ core\                       # 公共基础设施（与功能无关）
│  ├─ base_module.py           # 模块基类：initialize / start / stop
│  ├─ models.py                # 数据模型：HardwareInfo / ResourceSnapshot
│  └─ ring_buffer.py           # 环形缓冲（最近 60 帧，画趋势曲线）
└─ modules\
   └─ system_monitor\          # 【第一步】系统检测模块
      ├─ module.py             # 模块生命周期实现
      ├─ hardware_info.py      # 硬件检测（WMI + psutil + 注册表兜底）
      ├─ resource_monitor.py   # 资源监控（后台线程 1s 一帧，支持暂停/恢复）
      └─ ui.py                 # 浅色工具箱风格界面（10 项导航 + 系统状态页 + 硬件状态页）
```

## 界面导航（v0.1.1）

左侧导航共 10 项，按批次逐步开放：

| 导航项 | 状态 | 内容 |
|---|---|---|
| 系统状态 | ✅ 已实现 | 开机状态（上次开机时间）+ CPU（频率/利用率/进程/线程/句柄/虚拟化）+ GPU（利用率/专用显存）+ RAM（使用量/已提交/已缓存/分页池/非分页池）+ 网卡（速率/类型/实时收发/信号强度）+ 主板 + **硬盘（一硬盘一卡：容量/占用/读速/写速）** + 系统操作；页面可滚轮滚动 |
| 硬件状态 | ✅ 已实现 | GPU 专用信息栏（顶部实时：利用率/显存/驱动）+ CPU/GPU/RAM/主板/网卡/硬盘/操作系统 七张信息卡 + 检测控制 |
| 网络流量监测 | ⏳ 占位 | 待开发 |
| 进程监测 | ⏳ 占位 | 待开发 |
| 服务项监测 | ⏳ 占位 | 待开发 |
| 系统启动项管理 | ⏳ 占位 | 待开发 |
| 默认软件管理 | ⏳ 占位 | 待开发 |
| 右键菜单管理 | ⏳ 占位 | 待开发 |
| 高级功能 | ⏳ 占位 | 待开发 |
| 软件设置 | ⏳ 占位 | 待开发 |

## 环境要求

- Windows 10/11
- Python 3.10+（当前项目按 `D:\Program Files\Python314` 配置）
- 依赖：`pip install -r requirements.txt`
  （psutil / wmi / pywin32 / GPUtil，GPUtil 仅 NVIDIA 独显使用，装不上也不影响其他功能）

## 运行方式

1. 双击 **启动测试版.vbs**（推荐）—— 零窗口闪现，静默启动
2. 双击 **启动测试版.bat** —— 启动时会闪一下命令窗口（.bat 特性，不影响使用）
3. 双击 **运行自检.bat** —— 不开界面，控制台验证硬件检测 + 3 帧采样
4. 手动：`python main.py` 或 `python self_test.py`

> 单实例保护：程序通过命名互斥体保证只运行一个实例。重复启动时不会多开窗口，
> 而是弹一个「已在运行」提示框并自动退出。

## 已实现功能

| 功能 | 数据来源 | 说明 |
|---|---|---|
| CPU 型号/核心/线程/主频 | WMI Win32_Processor + psutil | 型号读注册表兜底 |
| 主板 / BIOS | WMI Win32_BaseBoard / _BIOS | |
| 显卡型号/显存/驱动 | WMI Win32_VideoController | AdapterRAM 可能封顶 4GB，仅供参考 |
| 内存条 容量/频率/插槽 | WMI Win32_PhysicalMemory | |
| 硬盘型号/容量/接口 | WMI Win32_DiskDrive | |
| 物理网卡 MAC/IP | WMI Win32_NetworkAdapter + psutil | 自动过滤虚拟网卡 |
| 系统版本/Build/开机时长 | WMI + psutil.boot_time | |
| CPU / 内存实时占用 | psutil（两次采样差值） | 每秒一帧 |
| 磁盘读/写速率 | disk_io_counters 差值 | MB/s |
| 网络上行/下行速率 | net_io_counters 差值 | MB/s，过滤回环 |
| 分区占用率 | psutil.disk_partitions + disk_usage | |
| GPU 利用率/显存 | nvidia-smi（CREATE_NO_WINDOW 静默） | 3 秒缓存，非 N 卡显示占位 |
| CPU 频率/进程/线程/句柄 | psutil | 进程/线程/句柄累加统计 |
| 内存 已提交 | GlobalMemoryStatusEx | 与任务管理器同口径 |
| 内存 已缓存/分页池/非分页池 | WMI PerfOS_Memory | 2 秒缓存 |
| 网卡当前速率/类型 | PowerShell Get-NetAdapter | 10 秒缓存，Wi-Fi/以太网 |
| Wi-Fi 信号强度 | netsh wlan show interfaces | 10 秒缓存，实测 82% |
| CPU 虚拟化 | WMI VirtualizationFirmwareEnabled | 界面显示 已启用/未启用 |
| 进程 TOP（按内存） | psutil.process_iter | 硬件状态页展示前 5 个 |

## 已知限制（测试版）

1. **温度/电压/风扇传感器**尚未实现 —— WMI 拿不到，需引入 LibreHardwareMonitor 的 Python 封装或其后端服务，留待下一步。
2. **GPU 仅支持 NVIDIA**（直接调 nvidia-smi，已用 CREATE_NO_WINDOW 隐藏控制台窗口，3 秒缓存一次）；A 卡需 ADL，后续可扩展。
3. **WMI 显存字段不可靠**：笔记本/部分驱动下 AdapterRAM 返回 0 或负数，测试版直接显示「未知」；实时显存/利用率由 nvidia-smi 提供。
4. 首次启动硬件检测需 1~2 秒（WMI 连接开销），界面已提示。
5. 第一帧速率类指标为 0（差值算法天然如此），第二帧起正常。

## 打包成 exe（即开即用）

1. 首次：`pip install --user pyinstaller`（已装可跳过）
2. 双击 **build.bat**，产物输出到 `dist\WindowsToolBox.exe`（约 1~2 分钟）
3. 以后改了代码，重新双击 build.bat 即可覆盖编译

关键参数说明：
- `--onefile`：单文件自解压；首次启动要解压到临时目录，比源码版慢 1~3 秒
- `--windowed`：无控制台窗口（等价于 pythonw）；冻结模式下 `sys.stdout` 为 None，main.py 已做空设备重定向
- `--icon icon.ico`：应用图标（`make_icon.py` 可重新生成）
- `--hidden-import wmi / win32com.client / pythoncom / pywintypes`：WMI 走 COM，需显式带上
- 后续做改 Hosts、服务启停等**管理员功能**时，打包命令加 `--uac-admin` 让 exe 自动请求提权

注意事项：
- 未签名 exe 首次运行可能被 SmartScreen 拦截，点「更多信息 → 仍要运行」即可
- 单文件版每次启动解压到 %TEMP%，杀软扫描会拖慢首启；追求启动速度可改用 `--onedir`
- 进阶优化：Nuitka 真编译（体积更小、更难反编译），等软件功能定型后再考虑

## 后续路线（架构已预留）

1. 传感器温度监控（LibreHardwareMonitor）
2. 启动项/服务管理（注册表 + win32service）
3. 流量监控（每进程网络计数，per-connection 统计）
4. 弹窗拦截 / 垃圾清理 / 右键管理 / 改 Host / DHCP 检测（各自独立成模块）

---

**模块化设计说明**：新功能 = 在 `modules\` 下新建包 + 实现 `BaseModule` 三个方法 + 在 `main.py` 注册。界面、数据、采集三层解耦，任何模块失败不影响其他模块。
