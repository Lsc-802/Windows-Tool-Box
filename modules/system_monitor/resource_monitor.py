# -*- coding: utf-8 -*-
"""
资源监控 —— 后台线程每 1 秒采集一帧 ResourceSnapshot，写入环形缓冲。

技术实现原理（重点）：
1. 「速率类」指标（磁盘 I/O、网络速率）不可能一次采样拿到，
   必须连续两次采样做差值 ÷ 时间间隔：
        MB/s = (本次字节数 - 上次字节数) / 1024² / 采样间隔
   psutil 的 disk_io_counters / net_io_counters 返回的是「累计字节数」。

2. CPU 使用率同理：psutil.cpu_percent() 内部用两次采样的差值计算。
   注意第一次调用会返回 0（还没拿到上一次采样），所以 __init__ 里先预热一次。

3. 线程模型：采集放在后台守护线程里做，界面线程每秒从 latest 取最新帧渲染，
   两者互不阻塞。采集失败不会让整个程序崩溃，只记录错误并继续下一轮。
"""
from __future__ import annotations

import ctypes
import re
import subprocess
import threading
import time
from typing import Optional

import psutil

from core.models import ResourceSnapshot, ProcessInfo, DiskStat
from core.ring_buffer import RingBuffer


def _read_gpu():
    """直接调用 nvidia-smi 读取 GPU（利用率 / 显存已用 / 显存总量）。

    为什么不用 GPUtil：
    GPUtil 内部用 subprocess.Popen 启动 nvidia-smi 时没有传
    CREATE_NO_WINDOW 标志 —— 在 pythonw（无控制台的 GUI 进程）下，
    每次调用都会闪出一个新的控制台黑框。我们这里显式隐藏窗口，
    并在调用方做 3 秒缓存，避免每秒都启动一次外部进程。
    返回 (利用率%, 显存已用MB, 显存总量MB)；失败返回 None。
    """
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW)  # 关键：不弹控制台窗口
        line = (out.stdout or "").strip().splitlines()
        if not line:
            return None
        parts = [p.strip() for p in line[0].split(",")]
        if len(parts) >= 3:
            return float(parts[0]), float(parts[1]), float(parts[2])
    except Exception:
        pass
    return None


# ------------------------------------------------------------------
# 系统状态页新增的采集
# ------------------------------------------------------------------

def _global_memory_status() -> Optional[float]:
    """GlobalMemoryStatusEx：返回「已提交内存」GB。
    已提交 = 物理内存承诺 + 页文件承诺，是判断内存压力最重要的指标之一。
    """
    try:
        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        ms = _MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        if not ok:
            return None
        committed = (ms.ullTotalPageFile - ms.ullAvailPageFile) / 1024 ** 3
        return round(committed, 2)
    except Exception:
        return None


_wmi_perf = None


def _read_pool() -> Optional[tuple]:
    """WMI 性能计数器：分页池 / 非分页池（MB）+ 系统缓存（MB）。
    用性能对象 Win32_PerfFormattedData_PerfOS_Memory，缓存 2 秒由调用方控制。
    """
    global _wmi_perf
    try:
        import wmi
        if _wmi_perf is None:
            _wmi_perf = wmi.WMI(namespace="root\\cimv2")
        for m in _wmi_perf.Win32_PerfFormattedData_PerfOS_Memory():
            paged = getattr(m, "PoolPagedBytes", None)
            nonpaged = getattr(m, "PoolNonpagedBytes", None)
            cache = getattr(m, "CacheBytes", None)
            if paged is not None and nonpaged is not None:
                return (float(paged) / 1024 ** 2,
                        float(nonpaged) / 1024 ** 2,
                        float(cache) / 1024 ** 2 if cache is not None else None)
            break
    except Exception:
        pass
    return None


_wmi_net = None


def _read_net_adapter() -> Optional[tuple]:
    """当前活动网卡的连接信息：(速率 Mbps, 类型)。

    用 Win32_NetworkAdapter 的 Speed 字段（实时链路速率，Wi-Fi 为当前
    PHY 速率，本机实测 544.5 Mbps）。比 PowerShell Get-NetAdapter 快约
    2 秒，避免采样线程被进程启动阻塞。类型按网卡名判定 Wi-Fi/以太网。
    缓存 10 秒由调用方控制。
    """
    global _wmi_net
    try:
        import wmi
        if _wmi_net is None:
            _wmi_net = wmi.WMI(namespace="root\\cimv2")
        best = None
        for a in _wmi_net.Win32_NetworkAdapter():
            try:
                enabled = bool(a.NetEnabled)
            except Exception:
                continue
            if not enabled:
                continue
            name = str(getattr(a, "Name", "") or "")
            low = name.lower()
            if any(k in low for k in ("virtual", "loopback", "bluetooth",
                                      "vpn", "pseudo", "remote", "docker",
                                      "radmin", "hyper-v")):
                continue
            speed = getattr(a, "Speed", None)
            try:
                speed = float(speed)
            except (TypeError, ValueError):
                continue
            if speed <= 0:
                continue
            typ = ("Wi-Fi" if any(k in low for k in ("wi-fi", "wlan",
                                                    "wireless"))
                   else "以太网")
            if best is None or speed > best[0]:
                best = (speed / 1e6, typ)
        return best
    except Exception:
        return None


def _read_wifi_signal() -> Optional[int]:
    """netsh 解析当前 Wi-Fi 信号强度（%）。
    输出语言可能是中文或英文，两种都匹配。缓存 10 秒由调用方控制。
    """
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"],
                             capture_output=True, text=True, timeout=4,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        for line in (out.stdout or "").splitlines():
            m = re.search(r"(?:Signal|信号)\s*:\s*(\d+)\s*%", line)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


def _disk_partition_map() -> dict:
    """构建 盘符('C:') → 物理硬盘设备号('PHYSICALDRIVE0') 的静态映射。

    用两条 WMI 关联类拼接：Win32_LogicalDiskToPartition（盘符→分区）
    + Win32_DiskDriveToDiskPartition（分区→物理盘）。只查一次，不变化。
    失败时返回 {}，界面退化为「仅显示整机 I/O」。
    """
    try:
        import wmi
        c = wmi.WMI(namespace="root\\cimv2")
        part_to_disk = {}
        for assoc in c.Win32_DiskDriveToDiskPartition():
            try:
                ant = getattr(assoc, "Antecedent", None)
                dep = getattr(assoc, "Dependent", None)
                part = getattr(dep, "DeviceID", None) or ""
                dev = getattr(ant, "DeviceID", None) or ""
            except Exception:
                continue
            part_to_disk[str(part)] = str(dev).replace("\\\\.\\", "").upper()
        drive_to_part = {}
        for assoc in c.Win32_LogicalDiskToPartition():
            try:
                dep = getattr(assoc, "Dependent", None)
                ant = getattr(assoc, "Antecedent", None)
                drive = getattr(dep, "DeviceID", None) or ""
                part = getattr(ant, "DeviceID", None) or ""
            except Exception:
                continue
            drive_to_part[str(drive)] = str(part)
        result = {}
        for drive, part in drive_to_part.items():
            disk = part_to_disk.get(part)
            if disk:
                result[drive.upper()] = disk
        return result
    except Exception:
        return {}


class ResourceMonitor:
    def __init__(self, interval: float = 1.0, history: int = 60):
        self.interval = interval
        self._history = RingBuffer(history)   # 最近 60 帧，供趋势曲线
        self._latest: Optional[ResourceSnapshot] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._paused = False  # 界面「暂停监控」用：暂停期间不采集新帧
        self.last_error: Optional[str] = None

        # —— 差值算法的两个基准点：首次调用时先记录，保证第一帧速率为 0 ——
        self._prev_net_up, self._prev_net_down = self._net_totals()
        self._prev_disk_read, self._prev_disk_write = self._disk_totals()
        # GPU 读取缓存（3 秒一次，避免频繁启动 nvidia-smi 外部进程）
        self._gpu_interval = 3.0
        self._gpu_cache = None
        self._gpu_cache_ts = 0.0
        # 内存池/网卡/信号缓存（慢速来源，各自独立节流）
        self._pool_cache = None
        self._pool_cache_ts = 0.0
        self._net_adapt_cache = None
        self._net_adapt_cache_ts = 0.0
        self._wifi_cache = None
        self._wifi_cache_ts = 0.0
        # 每盘 I/O 差值基准 + 分区→物理盘静态映射（懒加载）
        self._disk_io_prev = None
        self._disk_part_map: Optional[dict] = None
        # 进程/线程/句柄全量枚举开销大（约 300 进程），5 秒缓存一次
        self._proc_stats = (0, 0, [])
        self._proc_stats_ts = 0.0
        # CPU 百分比预热：第一次调用返回 0 且不产生真实数据，先丢掉
        psutil.cpu_percent(interval=None)

    # ------------------------------------------------------------------
    # 累计值取数（速率差值的原料）
    # ------------------------------------------------------------------

    @staticmethod
    def _net_totals() -> tuple:
        """汇总所有物理网卡的累计上行/下行字节数。"""
        up = down = 0.0
        try:
            data = psutil.net_io_counters(pernic=True)
            for name, cnt in data.items():
                if "loopback" in name.lower():
                    continue
                down += cnt.bytes_recv
                up += cnt.bytes_sent
        except Exception:
            pass
        return up, down

    @staticmethod
    def _disk_totals() -> tuple:
        """汇总所有磁盘的累计读/写字节数。"""
        try:
            cnt = psutil.disk_io_counters()  # 全盘聚合
            if cnt is None:
                return 0.0, 0.0
            return cnt.read_bytes, cnt.write_bytes
        except Exception:
            return 0.0, 0.0

    # ------------------------------------------------------------------
    # 单帧采集
    # ------------------------------------------------------------------

    def _sample(self) -> ResourceSnapshot:
        now = time.time()
        snap = ResourceSnapshot(ts=now)

        # CPU：总占用 + 每核心占用 + 当前实际频率
        snap.cpu_percent = psutil.cpu_percent(interval=None) or 0.0
        snap.cpu_per_core = [
            v or 0.0 for v in psutil.cpu_percent(interval=None, percpu=True)]
        freq = psutil.cpu_freq()
        snap.cpu_freq_mhz = round(freq.current, 0) if freq else None

        # 内存
        mem = psutil.virtual_memory()
        snap.mem_total_gb = round(mem.total / 1024 ** 3, 2)
        snap.mem_used_gb = round(mem.used / 1024 ** 3, 2)
        snap.mem_percent = round(mem.percent, 1)
        snap.ram_committed_gb = _global_memory_status()
        # 分页/非分页缓冲池 + 系统缓存：WMI 性能计数器，5 秒一次
        if now - self._pool_cache_ts >= 5.0:
            self._pool_cache = _read_pool()
            self._pool_cache_ts = now
        if self._pool_cache:
            snap.ram_paged_pool_mb = round(self._pool_cache[0], 1)
            snap.ram_nonpaged_pool_mb = round(self._pool_cache[1], 1)
            if self._pool_cache[2] is not None:
                snap.ram_cached_gb = round(self._pool_cache[2] / 1024, 2)

        # 磁盘 I/O 速率 = 差值 / 时间
        r, w = self._disk_totals()
        dt = max(self.interval, 1e-6)
        snap.disk_read_mbps = round((r - self._prev_disk_read) / 1024 ** 2 / dt, 2)
        snap.disk_write_mbps = round((w - self._prev_disk_write) / 1024 ** 2 / dt, 2)
        self._prev_disk_read, self._prev_disk_write = r, w

        # 网络速率 = 差值 / 时间
        up, down = self._net_totals()
        snap.net_down_mbps = round((down - self._prev_net_down) / 1024 ** 2 / dt, 2)
        snap.net_up_mbps = round((up - self._prev_net_up) / 1024 ** 2 / dt, 2)
        self._prev_net_up, self._prev_net_down = up, down

        # 网卡连接速率/类型：10 秒一次；信号强度：10 秒一次（仅无线）
        if now - self._net_adapt_cache_ts >= 10.0:
            self._net_adapt_cache = _read_net_adapter()
            self._net_adapt_cache_ts = now
        if self._net_adapt_cache:
            snap.net_speed_mbps = round(self._net_adapt_cache[0], 0)
            snap.net_type = self._net_adapt_cache[1]
        if now - self._wifi_cache_ts >= 10.0:
            self._wifi_cache = _read_wifi_signal()
            self._wifi_cache_ts = now
        snap.wifi_signal = self._wifi_cache

        # 每块物理硬盘实时状态：perdisk I/O 差值 + 分区占用聚合
        snap.disk_stats = []
        try:
            io_now = psutil.disk_io_counters(perdisk=True) or {}
            if self._disk_io_prev is not None:
                for dev, cur in io_now.items():
                    prev = self._disk_io_prev.get(dev)
                    if not prev:
                        continue
                    snap.disk_stats.append(DiskStat(
                        device_id=dev.upper(),
                        read_mbps=round(
                            max(0.0, cur.read_bytes - prev.read_bytes) / 1024 ** 2 / dt, 2),
                        write_mbps=round(
                            max(0.0, cur.write_bytes - prev.write_bytes) / 1024 ** 2 / dt, 2),
                    ))
            self._disk_io_prev = io_now
            # 分区占用率 → 同时产出整机 disk_usage 和按物理盘聚合
            if self._disk_part_map is None:
                self._disk_part_map = _disk_partition_map()
            snap.disk_usage = []
            part_usage = {}
            for p in psutil.disk_partitions():
                if "cdrom" in p.opts or not p.mountpoint:
                    continue
                drive = (p.device or "").rstrip("\\").upper()  # "C:\" → "C:"
                try:
                    u = psutil.disk_usage(p.mountpoint)
                except Exception:
                    continue
                snap.disk_usage.append((p.device, u.percent))
                disk = self._disk_part_map.get(drive)
                if disk:
                    used, total = part_usage.get(disk, (0.0, 0.0))
                    part_usage[disk] = (used + u.used, total + u.total)
            for st in snap.disk_stats:
                used, total = part_usage.get(st.device_id, (0.0, 0.0))
                if total > 0:
                    st.size_gb = round(total / 1024 ** 3, 1)
                    st.used_gb = round(used / 1024 ** 3, 1)
                    st.free_gb = round((total - used) / 1024 ** 3, 1)
                    st.percent = round(used / total * 100, 1)
        except Exception:
            pass

        # GPU（仅 NVIDIA）：3 秒缓存，防止每秒启动 nvidia-smi 弹控制台窗口
        if now - self._gpu_cache_ts >= self._gpu_interval:
            self._gpu_cache = _read_gpu()
            self._gpu_cache_ts = now
        if self._gpu_cache:
            g_util, g_used, g_total = self._gpu_cache
            snap.gpu_percent = round(g_util, 1)
            snap.gpu_mem_used_mb = round(g_used, 0)
            snap.gpu_mem_total_mb = round(g_total, 0)

        # 进程/线程/句柄：全量枚举开销大（约 300 进程 × 2 次句柄打开），
        # 10 秒缓存一次；每秒只取轻量的进程总数。
        snap.proc_count = len(psutil.pids())
        if now - self._proc_stats_ts >= 10.0:
            thread_count = handle_count = 0
            procs = []
            try:
                for p in psutil.process_iter(
                        ["pid", "name", "cpu_percent", "memory_info",
                         "num_threads", "num_handles"]):
                    try:
                        nt = p.info["num_threads"] or 0
                        thread_count += nt
                        nh = p.info["num_handles"] or 0
                        handle_count += nh
                        name = p.info["name"] or "?"
                        mem_mb = (p.info["memory_info"].rss or 0) / 1024 ** 2
                        procs.append((name, p.info["pid"],
                                      p.info["cpu_percent"] or 0.0, mem_mb))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                self._proc_stats = (thread_count, handle_count, procs)
                self._proc_stats_ts = now
            except Exception:
                pass
        thread_count, handle_count, procs = self._proc_stats
        snap.thread_count = thread_count
        snap.handle_count = handle_count
        procs.sort(key=lambda x: x[3], reverse=True)  # 内存降序
        snap.top_processes = [
            ProcessInfo(pid=pid, name=name, cpu_percent=round(cpu, 1),
                        mem_mb=round(mem, 1))
            for name, pid, cpu, mem in procs[:8]
        ]

        return snap

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动后台采集线程（守护线程，主程序退出自动结束）。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="resource-monitor")
        self._thread.start()

    def _run(self) -> None:
        # 关键：采集线程要用 WMI（COM），必须在**本线程**显式初始化 COM。
        # 否则主线程创建过 COM 连接后，这里复用不到正确的线程公寓，
        # Win32_PerfFormattedData 等查询会静默失败（返回 None）。
        import pythoncom
        pythoncom.CoInitialize()
        try:
            while not self._stop_event.wait(self.interval):
                if self._paused:
                    continue  # 暂停期间只计时，不采集
                try:
                    snap = self._sample()
                    self._history.push(snap)
                    self._latest = snap
                except Exception as e:
                    self.last_error = str(e)
        finally:
            pythoncom.CoUninitialize()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    # ------------------------------------------------------------------
    # 对外读取
    # ------------------------------------------------------------------

    @property
    def latest(self) -> Optional[ResourceSnapshot]:
        return self._latest

    @property
    def history(self) -> RingBuffer:
        return self._history
