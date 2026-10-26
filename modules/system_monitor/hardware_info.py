# -*- coding: utf-8 -*-
"""
硬件检测 —— 通过 WMI + psutil 采集硬件型号信息。

技术实现原理：
1. WMI（Windows Management Instrumentation）
   Windows 自带的系统管理接口，通过 COM 查询 Win32_* 类就能拿到
   几乎全部硬件清单（CPU/主板/BIOS/显卡/内存/硬盘/网卡/系统）。
   一个 WMI 连接开销不小（约几百 ms），所以用模块级单例复用。

2. psutil
   纯 Python 的跨平台系统库，负责取核心数、实时频率等 WMI 拿起来费劲的数据。

3. 容错设计
   每个采集函数都 try/except 包裹：某个硬件查不到（比如无独显、虚拟机里
   没有 Win32_BaseBoard 数据），只让该项变「未知」，绝不让整个采集崩溃。
   即使 wmi 库没装上，也能用注册表 + psutil 兜底拿到 CPU 型号。
"""
from __future__ import annotations

import time
from typing import Optional

import psutil

from core.models import (CPUInfo, MotherboardInfo, GPUInfo, RAMModule,
                         DiskInfo, NetworkAdapter, SystemInfo, HardwareInfo)

# ------------------------------------------------------------------
# WMI 连接单例：整个采集过程只建一次连接
# ------------------------------------------------------------------
_wmi_conn = None


def _wmi():
    """惰性创建并复用 WMI 连接；wmi 库不可用时返回 None。"""
    global _wmi_conn
    if _wmi_conn is not None:
        return _wmi_conn
    try:
        import wmi  # wmi 是 pywin32 COM 的封装
        _wmi_conn = wmi.WMI()
    except Exception:
        _wmi_conn = None
    return _wmi_conn


def _cpu_name_from_registry() -> Optional[str]:
    """兜底方案：从注册表读 CPU 型号名（不依赖 wmi 库）。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        winreg.CloseKey(key)
        return val
    except OSError:
        return None


def _safe(fn, default=None):
    """执行 fn，任何异常都返回 default。"""
    try:
        return fn()
    except Exception:
        return default


def _as_int(v):
    """把 WMI 返回的数值安全转成 int。
    兼容性说明：不同系统/WMI 版本可能返回 int、float 或字符串（如 "8589934592"），
    统一先转 float 再转 int，转换失败返回 None 而不是抛异常。
    """
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------
# 分类采集
# ------------------------------------------------------------------

def _collect_cpu() -> CPUInfo:
    info = CPUInfo()
    c = _wmi()
    base_mhz = None
    if c is not None:
        for p in c.Win32_Processor():
            name = getattr(p, "Name", None)
            if name:
                info.name = str(name).strip()
            base_mhz = getattr(p, "MaxClockSpeed", None)  # kHz 单位
            # 虚拟化启用状态（VT-x/AMD-V）：Win8+ 系统有该属性，值为 True/False
            v = getattr(p, "VirtualizationFirmwareEnabled", None)
            if v is True:
                info.virtualization = "已启用"
            elif v is False:
                info.virtualization = "未启用"
            else:
                info.virtualization = "未知"
            break
    if info.name == "未知":
        info.name = _cpu_name_from_registry() or "未知"

    info.cores = psutil.cpu_count(logical=False)
    info.threads = psutil.cpu_count(logical=True)
    freq = _safe(lambda: psutil.cpu_freq())
    if freq is not None:
        info.current_freq_ghz = round(freq.current / 1000.0, 2)
        if base_mhz is None and getattr(freq, "max", None):
            base_mhz = freq.max
    base_mhz = _as_int(base_mhz)
    if base_mhz:
        info.base_freq_ghz = round(base_mhz / 1000.0, 2)
    return info


def _collect_motherboard() -> MotherboardInfo:
    info = MotherboardInfo()
    c = _wmi()
    if c is None:
        return info
    for b in c.Win32_BaseBoard():
        info.manufacturer = getattr(b, "Manufacturer", None) or "未知"
        info.product = getattr(b, "Product", None) or "未知"
        break
    for b in c.Win32_BIOS():
        info.bios_vendor = getattr(b, "Manufacturer", None) or "未知"
        info.bios_version = getattr(b, "SMBIOSBIOSVersion", None) or "未知"
        date = getattr(b, "ReleaseDate", None)  # 形如 20230418000000.000000+480
        info.bios_date = str(date)[:8] if date else "未知"
        break
    return info


def _collect_gpus() -> list:
    """采集显卡。注意：WMI 的 AdapterRAM 在部分系统上封顶 4GB，显存仅供参考。"""
    gpus = []
    c = _wmi()
    if c is None:
        return gpus
    for v in c.Win32_VideoController():
        vram_b = _as_int(getattr(v, "AdapterRAM", None))
        # AdapterRAM 在部分笔记本/驱动下会返回异常值（0 或负数），一律当未知处理
        vram_mb = round(vram_b / 1024 / 1024) if vram_b and vram_b > 0 else None
        gpus.append(GPUInfo(
            name=str(getattr(v, "Name", None) or "未知").strip(),
            vram_mb=vram_mb,
            driver_version=str(getattr(v, "DriverVersion", None) or "未知"),
        ))
    return gpus


def _collect_rams() -> list:
    rams = []
    c = _wmi()
    if c is None:
        return rams
    for m in c.Win32_PhysicalMemory():
        cap = _as_int(getattr(m, "Capacity", None))
        rams.append(RAMModule(
            capacity_gb=round(cap / 1024 ** 3, 2) if cap else None,
            speed_mhz=_as_int(getattr(m, "Speed", None)) or None,
            manufacturer=str(getattr(m, "Manufacturer", None) or "未知"),
            slot=str(getattr(m, "DeviceLocator", None) or "未知"),
        ))
    return rams


def _collect_disks() -> list:
    disks = []
    c = _wmi()
    if c is None:
        return disks
    for d in c.Win32_DiskDrive():
        size = _as_int(getattr(d, "Size", None))
        dev = str(getattr(d, "DeviceID", "") or "").replace("\\\\.\\", "")
        disks.append(DiskInfo(
            model=str(getattr(d, "Model", None) or "未知").strip(),
            size_gb=round(size / 1024 ** 3, 1) if size else None,
            interface=str(getattr(d, "InterfaceType", None) or "未知"),
            device_id=dev.upper(),
        ))
    return disks


def _collect_networks() -> list:
    """只采集物理网卡（过滤虚拟网卡/回环）。

    兼容性说明：WMI 的 Win32_NetworkAdapter.Name 与 psutil.net_if_addrs 的键名
    经常对不上（一个是完整描述、一个是短名），所以 IP 不从 psutil 匹配，
    改用 Win32_NetworkAdapterConfiguration（它同时带 MAC 和 IP，按 MAC 配对最可靠）。
    """
    nets = []
    c = _wmi()
    if c is None:
        return nets
    # 先收集「MAC → IPv4 列表」映射
    mac_to_ips = {}
    try:
        for cfg in c.Win32_NetworkAdapterConfiguration():
            if not getattr(cfg, "IPEnabled", False):
                continue
            mac = str(getattr(cfg, "MACAddress", None) or "").upper()
            ips = list(getattr(cfg, "IPAddress", None) or [])
            ips = [ip for ip in ips if ":" not in ip]  # 只保留 IPv4
            if mac:
                mac_to_ips.setdefault(mac, []).extend(ips)
    except Exception:
        pass
    # 再遍历物理网卡并按 MAC 取 IP
    for n in c.Win32_NetworkAdapter():
        # PhysicalAdapter 属性在 Win8+ 才存在；不存在时默认当作物理网卡
        try:
            if not n.PhysicalAdapter:
                continue
        except Exception:
            pass
        name = str(getattr(n, "Name", None) or "未知")
        # 再过滤掉明显的虚拟网卡
        low = name.lower()
        if any(k in low for k in ("virtual", "loopback", "bluetooth", "vpn")):
            continue
        mac = str(getattr(n, "MACAddress", None) or "未知").upper()
        nets.append(NetworkAdapter(name=name, mac=mac,
                                   ips=mac_to_ips.get(mac, [])))
    return nets


def _collect_system() -> SystemInfo:
    info = SystemInfo()
    c = _wmi()
    if c is not None:
        for cs in c.Win32_ComputerSystem():
            info.manufacturer = str(getattr(cs, "Manufacturer", None) or "未知")
            info.model = str(getattr(cs, "Model", None) or "未知")
            total = _as_int(getattr(cs, "TotalPhysicalMemory", None))
            info.total_ram_gb = round(total / 1024 ** 3, 1) if total else None
            break
        for os_ in c.Win32_OperatingSystem():
            info.os_caption = str(getattr(os_, "Caption", None) or "未知").strip()
            info.os_build = str(getattr(os_, "BuildNumber", None) or "未知")
            break
    # 开机时长用 psutil 的启动时间戳计算，不依赖 WMI
    boot = _safe(lambda: psutil.boot_time())
    if boot:
        uptime_s = max(0, int(time.time() - boot))
        days, rem = divmod(uptime_s, 86400)
        hours, rem = divmod(rem, 3600)
        mins = rem // 60
        parts = []
        if days:
            parts.append(f"{days}天")
        if hours:
            parts.append(f"{hours}小时")
        parts.append(f"{mins}分钟")
        info.uptime_text = "".join(parts)
        info.last_boot_text = time.strftime("%Y-%m-%d %H:%M:%S",
                                            time.localtime(boot))
    return info


# ------------------------------------------------------------------
# 对外总入口
# ------------------------------------------------------------------

def collect_hardware_info() -> HardwareInfo:
    """采集全部硬件信息并汇总为一个 HardwareInfo 对象。"""
    return HardwareInfo(
        cpu=_collect_cpu(),
        motherboard=_collect_motherboard(),
        gpus=_collect_gpus(),
        rams=_collect_rams(),
        disks=_collect_disks(),
        networks=_collect_networks(),
        system=_collect_system(),
    )
