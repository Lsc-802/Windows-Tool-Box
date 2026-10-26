# -*- coding: utf-8 -*-
"""
数据模型 —— 整个项目的数据契约。

设计逻辑：
采集层（WMI / psutil / 原生API）只负责把原始数据填进这些模型，
界面层只负责读模型渲染，两层之间不直接耦合。
以后任何模块（流量监控、进程管理等）都复用同一套模型，避免各写各的。

约定：
- 数值统一单位：内存/显存用 GB，磁盘/网络速率用 MB/s，温度用 ℃
- 所有字段允许 None 表示「未能采集到」，界面负责显示为「未知」
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, List, Tuple


# ============================================================
# 一、硬件信息（启动时查询一次，低频）
# ============================================================

@dataclass
class CPUInfo:
    name: str = "未知"                 # 型号名，如 "Intel(R) Core(TM) i7-10700K"
    cores: Optional[int] = None        # 物理核心数
    threads: Optional[int] = None      # 逻辑线程数
    base_freq_ghz: Optional[float] = None    # 基准主频 (GHz)
    current_freq_ghz: Optional[float] = None # 当前实时主频 (GHz)
    virtualization: str = "未知"       # 虚拟化（VT-x/AMD-V）是否已启用


@dataclass
class MotherboardInfo:
    manufacturer: str = "未知"   # 主板厂商
    product: str = "未知"        # 主板型号
    bios_vendor: str = "未知"    # BIOS 厂商
    bios_version: str = "未知"   # BIOS 版本
    bios_date: str = "未知"      # BIOS 日期


@dataclass
class GPUInfo:
    name: str = "未知"                # 显卡型号
    vram_mb: Optional[int] = None     # 显存 (MB)。注意：WMI 的 AdapterRAM 在 32 位系统/部分驱动下会封顶 4GB，仅供参考
    driver_version: str = "未知"      # 驱动版本


@dataclass
class RAMModule:
    capacity_gb: Optional[float] = None  # 单条容量 (GB)
    speed_mhz: Optional[int] = None      # 频率 (MHz)
    manufacturer: str = "未知"
    slot: str = "未知"                   # 插槽位置，如 "ChannelA-DIMM0"


@dataclass
class DiskInfo:
    model: str = "未知"                  # 硬盘型号
    size_gb: Optional[float] = None      # 物理容量 (GB)
    interface: str = "未知"              # 接口类型，如 SATA / NVMe
    device_id: str = ""                  # 设备号，如 "PhysicalDrive0"（用于和实时统计对齐）


@dataclass
class NetworkAdapter:
    name: str = "未知"                   # 网卡名
    mac: str = "未知"                    # MAC 地址
    ips: List[str] = field(default_factory=list)  # IPv4 列表


@dataclass
class SystemInfo:
    manufacturer: str = "未知"   # 设备制造商（品牌机才有值，DIY 通常是主板厂商）
    model: str = "未知"          # 设备型号
    total_ram_gb: Optional[float] = None  # 物理内存总量
    os_caption: str = "未知"     # 系统版本描述，如 "Microsoft Windows 11 专业版"
    os_build: str = "未知"       # 系统 Build 号
    uptime_text: str = "未知"    # 开机运行时长
    last_boot_text: str = "未知" # 上次开机具体时间，如 "2026-10-19 06:23:45"


@dataclass
class HardwareInfo:
    """硬件信息汇总对象：一次采集，整包交付给界面。"""
    cpu: CPUInfo = field(default_factory=CPUInfo)
    motherboard: MotherboardInfo = field(default_factory=MotherboardInfo)
    gpus: List[GPUInfo] = field(default_factory=list)
    rams: List[RAMModule] = field(default_factory=list)
    disks: List[DiskInfo] = field(default_factory=list)
    networks: List[NetworkAdapter] = field(default_factory=list)
    system: SystemInfo = field(default_factory=SystemInfo)

    def summary(self) -> str:
        """生成便于控制台自检打印的文本摘要。"""
        lines = []
        c = self.cpu
        lines.append(f"【处理器】 {c.name} | {c.cores}核{c.threads}线程"
                     f" | 基准 {c.base_freq_ghz} GHz | 当前 {c.current_freq_ghz} GHz")
        m = self.motherboard
        lines.append(f"【主板】   {m.manufacturer} {m.product}")
        lines.append(f"【BIOS】   {m.bios_vendor} {m.bios_version} ({m.bios_date})")
        for i, g in enumerate(self.gpus, 1):
            vram = f"{g.vram_mb} MB" if g.vram_mb else "未知"
            lines.append(f"【显卡{i}】 {g.name} | 显存 {vram} | 驱动 {g.driver_version}")
        for i, r in enumerate(self.rams, 1):
            lines.append(f"【内存{i}】 {r.capacity_gb} GB @ {r.speed_mhz} MHz"
                         f" ({r.manufacturer}, {r.slot})")
        for i, d in enumerate(self.disks, 1):
            lines.append(f"【硬盘{i}】 {d.model} | {d.size_gb} GB | {d.interface}")
        for i, n in enumerate(self.networks, 1):
            lines.append(f"【网卡{i}】 {n.name} | MAC {n.mac} | IP {', '.join(n.ips) or '未知'}")
        s = self.system
        lines.append(f"【系统】   {s.os_caption} (Build {s.os_build})")
        lines.append(f"【设备】   {s.manufacturer} {s.model} | 内存总量 {s.total_ram_gb} GB")
        lines.append(f"【运行】   已开机 {s.uptime_text}")
        return "\n".join(lines)


# ============================================================
# 二、资源快照（每 1 秒一帧，高频）
# ============================================================

@dataclass
class ProcessInfo:
    pid: int = 0
    name: str = "未知"
    cpu_percent: float = 0.0   # 进程 CPU 占用 %
    mem_mb: float = 0.0        # 进程内存占用 MB


@dataclass
class DiskStat:
    """某块物理硬盘的实时状态（每 1 秒一帧）。"""
    device_id: str = ""                 # PhysicalDriveN
    size_gb: Optional[float] = None     # 物理容量（由硬件信息补齐）
    used_gb: Optional[float] = None     # 已用（该盘所有挂载分区合计）
    free_gb: Optional[float] = None
    percent: Optional[float] = None     # 占用率（合计口径）
    read_mbps: float = 0.0
    write_mbps: float = 0.0


@dataclass
class ResourceSnapshot:
    """某一时刻的系统资源快照。"""
    ts: float = 0.0                       # 时间戳（time.time()）
    cpu_percent: float = 0.0              # CPU 总占用 %
    cpu_per_core: List[float] = field(default_factory=list)   # 每个逻辑核心占用 %
    cpu_freq_mhz: Optional[float] = None  # CPU 当前实际频率 MHz
    proc_count: int = 0                   # 运行中的进程总数
    thread_count: int = 0                 # 全部进程的线程总数
    handle_count: int = 0                 # 全部进程的句柄总数
    mem_total_gb: float = 0.0
    mem_used_gb: float = 0.0
    mem_percent: float = 0.0
    ram_committed_gb: Optional[float] = None   # 已提交内存（物理+页文件承诺）
    ram_cached_gb: Optional[float] = None      # 系统缓存
    ram_paged_pool_mb: Optional[float] = None  # 分页缓冲池
    ram_nonpaged_pool_mb: Optional[float] = None  # 非分页缓冲池
    net_speed_mbps: Optional[float] = None  # 网卡当前连接速率 Mbps
    net_type: str = "未知"                # 连接类型：以太网 / Wi-Fi
    wifi_signal: Optional[int] = None     # Wi-Fi 信号强度 %（仅无线时）
    disk_read_mbps: float = 0.0           # 磁盘读速率
    disk_write_mbps: float = 0.0          # 磁盘写速率
    net_down_mbps: float = 0.0            # 网络下行速率
    net_up_mbps: float = 0.0              # 网络上行速率
    gpu_percent: Optional[float] = None   # GPU 利用率（无独显/N卡时为 None）
    gpu_mem_used_mb: Optional[float] = None
    gpu_mem_total_mb: Optional[float] = None
    disk_usage: List[Tuple[str, float]] = field(default_factory=list)  # [(盘符, 占用%), ...]
    disk_stats: List[DiskStat] = field(default_factory=list)           # 每块物理硬盘实时状态
    top_processes: List[ProcessInfo] = field(default_factory=list)     # 内存占用最高的进程

    def summary_line(self) -> str:
        """一行摘要，用于自检打印。"""
        t = time.strftime("%H:%M:%S", time.localtime(self.ts))
        gpu = f" | GPU {self.gpu_percent:.0f}%" if self.gpu_percent is not None else ""
        freq = f"{self.cpu_freq_mhz:.0f}MHz" if self.cpu_freq_mhz else "--"
        committed = (f" | 已提交 {self.ram_committed_gb:.1f}G"
                     if self.ram_committed_gb is not None else "")
        net = f" | 网络 ↓ {self.net_down_mbps:.2f} ↑ {self.net_up_mbps:.2f} MB/s"
        return (f"[{t}] CPU {self.cpu_percent:.1f}% ({freq})"
                f" | 进程 {self.proc_count} 线程 {self.thread_count} 句柄 {self.handle_count}"
                f" | 内存 {self.mem_percent:.1f}%"
                f" ({self.mem_used_gb:.1f}/{self.mem_total_gb:.1f} GB){committed}"
                f" | 磁盘读 {self.disk_read_mbps:.2f} MB/s 写 {self.disk_write_mbps:.2f} MB/s"
                f"{net}{gpu}")
