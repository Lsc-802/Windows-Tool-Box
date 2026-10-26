# -*- coding: utf-8 -*-
"""
界面层 —— 浅色工具箱风格（参考安卓设备工具箱布局）。

系统状态页：开机状态卡 + CPU/GPU/RAM/网卡/主板 五张实时状态卡 + 系统操作卡
硬件状态页：GPU 专用信息栏（顶部实时）+ CPU/GPU/RAM/主板/网卡/硬盘/操作系统 信息卡 + 检测控制
其余导航项为后续模块占位。
刷新机制：后台线程每秒采集，界面每秒渲染。
"""
from __future__ import annotations

import subprocess
import time
import tkinter as tk
from tkinter import messagebox

from core.models import HardwareInfo
from modules.system_monitor.resource_monitor import ResourceMonitor

# ---------------- 浅色主题 ----------------
BG = "#F4F6F9"          # 窗口底色
CARD = "#FFFFFF"        # 卡片底色
SIDEBAR = "#FFFFFF"     # 侧栏底色
BORDER = "#E6E9EF"      # 分隔/边框
TEXT = "#2F3542"        # 主文字
SUB = "#7B8494"         # 次要文字
ACCENT = "#1677FF"      # 强调蓝
ACCENT_SOFT = "#E8F3FF" # 选中态浅蓝
OK = "#16A34A"
WARN = "#F59E0B"
DANGER = "#EF4444"

FONT = ("Microsoft YaHei UI", 10)
FONT_S = ("Microsoft YaHei UI", 9)
FONT_B = ("Microsoft YaHei UI", 11, "bold")
FONT_L = ("Microsoft YaHei UI", 22, "bold")
FONT_MONO = ("Consolas", 9)

# 趋势线配色
C_CPU = "#1677FF"
C_MEM = "#16A34A"
C_NET_DOWN = "#F59E0B"
C_NET_UP = "#EF4444"
C_DISK_R = "#7C3AED"
C_DISK_W = "#EC4899"

# 导航项：key → 显示名（未实现模块显示占位页）
NAV_ITEMS = [
    ("sys", "系统状态"),
    ("hw", "硬件状态"),
    ("net", "网络流量监测"),
    ("proc", "进程监测"),
    ("svc", "服务项监测"),
    ("startup", "系统启动项管理"),
    ("default", "默认软件管理"),
    ("context", "右键菜单管理"),
    ("adv", "高级功能"),
    ("settings", "软件设置"),
]

CREATE_NO_WINDOW = 0x08000000


def _pct_color(p: float) -> str:
    if p < 60:
        return OK
    if p < 85:
        return WARN
    return DANGER


class SystemMonitorUI:
    def __init__(self, root: tk.Tk, monitor: ResourceMonitor,
                 hardware: HardwareInfo):
        self.root = root
        self.monitor = monitor
        self.hardware = hardware

        root.title("Windows Tool Box 测试版 v0.1")
        root.configure(bg=BG)
        root.geometry("1120x780")
        root.minsize(960, 700)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._page = None          # 当前导航 key
        self._page_frame = None    # 当前页面容器
        self._nav_btns = {}        # key → 按钮
        self._gpu_bar_refs = {}    # 硬件页 GPU 信息栏引用
        self._sys_refs = {}        # 系统状态页各状态卡引用
        self._paused = False       # 检测控制卡按钮状态

        self._build_layout()
        self._show_page("sys")
        root.after(1000, self._tick)

    # ================================================================
    # 总体布局
    # ================================================================
    def _build_layout(self):
        # ---- 头部 ----
        header = tk.Frame(self.root, bg=CARD, highlightthickness=0)
        header.pack(fill=tk.X)
        tk.Label(header, text="Windows Tool Box", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 14, "bold"),
                 padx=16, pady=10).pack(side=tk.LEFT)
        tk.Label(header, text="测试版 v0.1", bg=CARD, fg=SUB,
                 font=FONT_S).pack(side=tk.LEFT, pady=(14, 0))
        self.hdr_status = tk.Label(header, text="", bg=CARD, fg=SUB, font=FONT_S)
        self.hdr_status.pack(side=tk.RIGHT, padx=16, pady=(13, 0))

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True)

        # ---- 侧栏 ----
        sidebar = tk.Frame(body, bg=SIDEBAR, width=176)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        self._build_sidebar(sidebar)

        # 侧栏右边线
        tk.Frame(body, bg=BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y)

        # ---- 页面容器（可滚动画布，小窗口时滚轮查看）----
        self._page_frame = tk.Frame(body, bg=BG)
        self._page_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._page_canvas = tk.Canvas(self._page_frame, bg=BG,
                                      highlightthickness=0)
        self._page_vsb = tk.Scrollbar(self._page_frame, orient=tk.VERTICAL,
                                      command=self._page_canvas.yview)
        self._page_canvas.configure(yscrollcommand=self._page_vsb.set)
        self._page_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._page_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._page_inner = tk.Frame(self._page_canvas, bg=BG)
        self._page_window = self._page_canvas.create_window(
            (0, 0), window=self._page_inner, anchor="nw")
        self._page_inner.bind("<Configure>", self._on_inner_configure)
        self._page_canvas.bind("<Configure>", self._on_canvas_configure)
        # 滚轮：Tk 事件按 bindtag 链（控件→类→顶层→"all"）传播，中间父容器
        # 不在链上。因此必须 bind_all（任何控件上的滚轮事件最终都会走到
        # "all" 环节），再配合 canvas 自身绑定的 "break" 避免双击触发。
        self._page_canvas.bind("<MouseWheel>", self._on_wheel)
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        self.root.bind_all("<Button-4>",
                           lambda e: self._page_canvas.yview_scroll(-3, "units"))
        self.root.bind_all("<Button-5>",
                           lambda e: self._page_canvas.yview_scroll(3, "units"))

        # ---- 状态栏 ----
        status = tk.Frame(self.root, bg=CARD, highlightthickness=1,
                          highlightbackground=BORDER)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_label = tk.Label(status, text="启动中…", bg=CARD, fg=SUB,
                                     font=FONT_S, anchor=tk.W, padx=14, pady=4)
        self.status_label.pack(fill=tk.X)

    def _build_sidebar(self, sidebar):
        # 侧栏顶部：设备状态块
        tk.Label(sidebar, text="设备状态", bg=SIDEBAR, fg=SUB,
                 font=FONT_S, anchor=tk.W).pack(fill=tk.X, padx=14, pady=(12, 2))
        self.sb_status = tk.Label(sidebar, text="", bg=SIDEBAR, fg=TEXT,
                                  font=FONT_S, anchor=tk.W, justify=tk.LEFT)
        self.sb_status.pack(fill=tk.X, padx=14, pady=(2, 10))
        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill=tk.X, padx=10)

        # 导航按钮
        for key, label in NAV_ITEMS:
            b = tk.Button(sidebar, text=label, font=FONT, anchor=tk.W,
                          relief=tk.FLAT, bd=0, cursor="hand2",
                          bg=SIDEBAR, fg=SUB, activebackground=ACCENT_SOFT,
                          activeforeground=ACCENT, padx=14, pady=7,
                          command=lambda k=key: self._show_page(k))
            b.pack(fill=tk.X, padx=8, pady=1)
            self._nav_btns[key] = b

        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill=tk.X, padx=10, pady=(8, 0))
        tk.Label(sidebar, text="v0.1 测试版 · 后续模块逐步加入",
                 bg=SIDEBAR, fg=SUB, font=("Microsoft YaHei UI", 8),
                 anchor=tk.W).pack(fill=tk.X, padx=14, pady=8)

        self._update_sidebar_status()

    def _update_sidebar_status(self):
        s = self.hardware.system
        self.sb_status.config(text=f"● 运行中\n平台  {self._arch()}\n"
                                   f"系统  {s.os_build}\n开机  {s.uptime_text}")
        self.hdr_status.config(
            text=f"● 运行中  ·  开机 {s.uptime_text}  ·  {self._arch()}")

    @staticmethod
    def _arch() -> str:
        import platform
        return platform.machine() or "未知"

    # ================================================================
    # 页面切换
    # ================================================================
    def _show_page(self, key: str):
        self._page = key
        for k, b in self._nav_btns.items():
            if k == key:
                b.config(bg=ACCENT_SOFT, fg=ACCENT, font=FONT_B)
            else:
                b.config(bg=SIDEBAR, fg=SUB, font=FONT)
        for w in self._page_inner.winfo_children():
            w.destroy()
        if key == "sys":
            self._build_system_status()
        elif key == "hw":
            self._build_hardware()
        else:
            self._build_placeholder(key)

    def _on_inner_configure(self, event):
        self._page_canvas.configure(scrollregion=self._page_canvas.bbox("all"))
        try:
            bbox = self._page_canvas.bbox("all")
            if bbox and bbox[3] <= self._page_canvas.winfo_height():
                self._page_vsb.pack_forget()   # 内容没超出一屏就隐藏滚动条
            else:
                self._page_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        except Exception:
            pass

    def _on_canvas_configure(self, event):
        self._page_canvas.itemconfigure(self._page_window, width=event.width)

    def _on_wheel(self, event):
        # 返回 "break" 终止本事件继续沿 bindtag 链传播（防止 canvas 自身
        # 与 bind_all 重复滚动）。
        if hasattr(event, "delta") and event.delta:
            step = max(1, abs(int(event.delta)) // 120) * 3
            self._page_canvas.yview_scroll(
                -step if event.delta > 0 else step, "units")
        else:
            self._page_canvas.yview_scroll(-3, "units")
        return "break"

    def _build_placeholder(self, key):
        name = dict(NAV_ITEMS).get(key, key)
        f = tk.Frame(self._page_inner, bg=BG)
        f.pack(fill=tk.BOTH, expand=True)
        card = tk.Frame(f, bg=CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=420, height=220)
        tk.Label(card, text=name, bg=CARD, fg=TEXT, font=FONT_B).pack(pady=(40, 6))
        tk.Label(card, text="该模块正在开发中\n架构已预留：modules\\ 下新建包即可接入",
                 bg=CARD, fg=SUB, font=FONT, justify=tk.CENTER).pack()

    # ================================================================
    # 硬件状态页：GPU 信息栏（顶）+ 硬件信息卡片
    # ================================================================
    def _build_hardware(self):
        outer = tk.Frame(self._page_inner, bg=BG)
        outer.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        # ---- GPU 专用信息栏（横贯顶部，实时刷新）----
        gpu_bar = tk.Frame(outer, bg=CARD, highlightthickness=1,
                           highlightbackground=BORDER)
        gpu_bar.pack(fill=tk.X)
        self._gpu_bar_refs = {}
        head = tk.Frame(gpu_bar, bg=CARD)
        head.pack(fill=tk.X, padx=16, pady=(10, 0))
        tk.Label(head, text="GPU 状态", bg=CARD, fg=TEXT, font=FONT_B).pack(side=tk.LEFT)
        self._gpu_bar_refs["name"] = tk.Label(
            head, text=self._main_gpu_name(), bg=CARD, fg=SUB, font=FONT_S,
            anchor=tk.W)
        self._gpu_bar_refs["name"].pack(side=tk.LEFT, padx=(14, 0))
        self._gpu_bar_refs["util"] = tk.Label(
            head, text="--%", bg=CARD, fg=TEXT,
            font=("Microsoft YaHei UI", 18, "bold"))
        self._gpu_bar_refs["util"].pack(side=tk.RIGHT)
        mid = tk.Frame(gpu_bar, bg=CARD)
        mid.pack(fill=tk.X, padx=16, pady=(4, 0))
        self._gpu_bar_refs["vram"] = tk.Label(mid, text="显存 --", bg=CARD,
                                              fg=TEXT, font=FONT)
        self._gpu_bar_refs["vram"].pack(side=tk.LEFT)
        self._gpu_bar_refs["shared"] = tk.Label(mid, text="共享显存 待接入",
                                                bg=CARD, fg=SUB, font=FONT_S)
        self._gpu_bar_refs["shared"].pack(side=tk.LEFT, padx=(14, 0))
        self._gpu_bar_refs["temp"] = tk.Label(mid, text="温度 待接入", bg=CARD,
                                              fg=SUB, font=FONT_S)
        self._gpu_bar_refs["temp"].pack(side=tk.LEFT, padx=(14, 0))
        driver_txt = (f"驱动 {self.hardware.gpus[0].driver_version}"
                      if self.hardware.gpus else "")
        self._gpu_bar_refs["driver"] = tk.Label(mid, text=driver_txt, bg=CARD,
                                                fg=SUB, font=FONT_S)
        self._gpu_bar_refs["driver"].pack(side=tk.RIGHT)
        self._gpu_bar_refs["bar"] = tk.Canvas(gpu_bar, height=8, bg=CARD,
                                              highlightthickness=0)
        self._gpu_bar_refs["bar"].pack(fill=tk.X, padx=16, pady=(6, 10))

        # ---- 硬件信息卡片（CPU / GPU / RAM / 主板 / 网卡 / 硬盘 / 操作系统）----
        grid = tk.Frame(outer, bg=BG)
        grid.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1, uniform="hw")
        self._build_hw_card(grid, 0, 0, "CPU", self._hw_cpu_rows())
        self._build_hw_card(grid, 0, 1, "GPU", self._hw_gpu_rows())
        self._build_hw_card(grid, 0, 2, "RAM", self._hw_ram_rows())
        self._build_hw_card(grid, 1, 0, "主板", self._hw_mb_rows())
        self._build_hw_card(grid, 1, 1, "网卡", self._hw_net_rows())
        self._build_hw_card(grid, 1, 2, "硬盘", self._hw_disk_rows())
        self._build_hw_card(grid, 2, 0, "操作系统", self._hw_os_rows(), span=3)

        # ---- 检测控制（保留在硬件页底部）----
        bottom = tk.Frame(outer, bg=BG)
        bottom.pack(fill=tk.X, pady=(8, 0))
        self._build_control_card(bottom)

    def _build_hw_card(self, parent, row, col, title, rows, span=1):
        card = tk.Frame(parent, bg=CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        card.grid(row=row, column=col, columnspan=span, sticky="nsew",
                  padx=4, pady=4)
        tk.Label(card, text=title, bg=CARD, fg=TEXT, font=FONT_B,
                 anchor=tk.W).pack(fill=tk.X, padx=12, pady=(8, 2))
        body = tk.Frame(card, bg=CARD)
        body.pack(fill=tk.X, padx=12, pady=(0, 8))
        for lab, val in rows:
            tk.Label(body, text=lab, bg=CARD, fg=SUB, font=FONT_S,
                     anchor=tk.W, width=9).grid(sticky="w", pady=1)
            tk.Label(body, text=val, bg=CARD, fg=TEXT, font=FONT_S,
                     anchor=tk.W, justify=tk.LEFT, wraplength=270).grid(
                row=body.grid_size()[1] - 1, column=1, sticky="w", pady=1)

    # ---- 各硬件卡内容 ----
    def _hw_cpu_rows(self):
        c = self.hardware.cpu
        return [("型号", c.name),
                ("核心 / 线程", f"{c.cores} 核 / {c.threads} 线程"),
                ("基准频率", f"{c.base_freq_ghz} GHz" if c.base_freq_ghz else "未知"),
                ("当前频率", f"{c.current_freq_ghz} GHz" if c.current_freq_ghz else "未知"),
                ("虚拟化", c.virtualization)]

    def _hw_gpu_rows(self):
        gpus = self.hardware.gpus
        if not gpus:
            return [("型号", "无独显 / 未检测到")]
        rows = []
        for g in gpus[:2]:
            vram = f"{g.vram_mb} MB" if g.vram_mb else "未知"
            rows += [("型号", g.name), ("显存", vram), ("驱动", g.driver_version)]
        return rows

    def _hw_ram_rows(self):
        hw = self.hardware
        rows = [("总量", f"{hw.system.total_ram_gb} GB")]
        for r in hw.rams:
            rows.append(("插槽", f"{r.capacity_gb} GB @ {r.speed_mhz} MHz · {r.manufacturer}"))
        return rows

    def _hw_mb_rows(self):
        m = self.hardware.motherboard
        return [("厂商", m.manufacturer), ("型号", m.product),
                ("BIOS 版本", m.bios_version), ("BIOS 日期", m.bios_date)]

    def _hw_net_rows(self):
        nets = self.hardware.networks or []
        rows = []
        for n in nets[:3]:
            rows += [("网卡", n.name),
                     ("MAC", n.mac),
                     ("IP", ", ".join(n.ips) if n.ips else "未连接")]
        return rows or [("网卡", "未知")]

    def _hw_disk_rows(self):
        rows = []
        for d in self.hardware.disks[:3]:
            rows.append(("硬盘", f"{d.model} · {d.size_gb} GB · {d.interface}"))
        return rows or [("硬盘", "未知")]

    def _hw_os_rows(self):
        s = self.hardware.system
        return [("系统", s.os_caption),
                ("Build", s.os_build),
                ("平台架构", self._arch()),
                ("上次开机", s.last_boot_text),
                ("开机时长", s.uptime_text)]

    # ---------------- 底部功能卡 ----------------
    def _build_action_card(self, parent):
        card = tk.Frame(parent, bg=CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        card.pack(fill=tk.X)
        tk.Label(card, text="系统操作", bg=CARD, fg=TEXT, font=FONT_B,
                 anchor=tk.W).pack(fill=tk.X, padx=12, pady=(8, 4))
        g = tk.Frame(card, bg=CARD)
        g.pack(pady=(0, 10), anchor=tk.CENTER)
        g.grid_columnconfigure((0, 1), weight=1, uniform="op")
        self._mk_btn(g, "锁屏", self._action_lock).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        self._mk_btn(g, "睡眠", self._action_sleep).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        self._mk_btn(g, "重启", self._action_restart).grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        self._mk_btn(g, "关机", self._action_shutdown).grid(row=1, column=1, sticky="ew", padx=3, pady=3)

    def _build_control_card(self, parent):
        card = tk.Frame(parent, bg=CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6)
        tk.Label(card, text="检测控制", bg=CARD, fg=TEXT, font=FONT_B,
                 anchor=tk.W).pack(fill=tk.X, padx=12, pady=(8, 4))
        g = tk.Frame(card, bg=CARD)
        g.pack(fill=tk.X, padx=10, pady=(0, 10))
        g.grid_columnconfigure((0, 1), weight=1, uniform="op")
        self._mk_btn(g, "刷新硬件", self._refresh_hardware).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        self._mk_btn(g, "复制硬件报告", self._copy_report).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        self.pause_btn = self._mk_btn(g, "暂停监控", self._toggle_pause)
        self.pause_btn.grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        self._mk_btn(g, "运行自检", self._run_selftest).grid(row=1, column=1, sticky="ew", padx=3, pady=3)

    # ---------------- 通用小按钮 ----------------
    def _mk_btn(self, parent, text, cmd, padx=6):
        return tk.Button(parent, text=text, command=cmd, font=FONT_S,
                         relief=tk.FLAT, bd=0, cursor="hand2",
                         bg=CARD, fg=TEXT, activebackground=ACCENT_SOFT,
                         activeforeground=ACCENT, padx=padx, pady=4,
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=BORDER)

    def _main_gpu_name(self) -> str:
        gpus = self.hardware.gpus
        if not gpus:
            return "无独显 / 未检测到"
        for g in gpus:
            if "NVIDIA" in g.name.upper():
                return g.name
        return gpus[0].name

    # ================================================================
    # 系统状态页：开机状态 + CPU/GPU/RAM/网卡/主板 实时状态
    # ================================================================
    def _build_system_status(self):
        outer = tk.Frame(self._page_inner, bg=BG)
        outer.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        # ---- 开机状态卡（横跨整行）----
        boot_card = tk.Frame(outer, bg=CARD, highlightthickness=1,
                             highlightbackground=BORDER)
        boot_card.pack(fill=tk.X)
        boot_inner = tk.Frame(boot_card, bg=CARD)
        boot_inner.pack(fill=tk.X, padx=16, pady=12)
        tk.Label(boot_inner, text="●", bg=CARD, fg=OK,
                 font=("Microsoft YaHei UI", 20)).pack(side=tk.LEFT, padx=(0, 10))
        left = tk.Frame(boot_inner, bg=CARD)
        left.pack(side=tk.LEFT)
        tk.Label(left, text="开机状态", bg=CARD, fg=SUB, font=FONT_S,
                 anchor=tk.W).pack(anchor=tk.W)
        self._sys_refs["boot"] = tk.Label(
            left, text="已运行 --", bg=CARD, fg=TEXT,
            font=("Microsoft YaHei UI", 18, "bold"))
        self._sys_refs["boot"].pack(anchor=tk.W)
        right = tk.Frame(boot_inner, bg=CARD)
        right.pack(side=tk.RIGHT)
        self._sys_refs["boot_time"] = tk.Label(
            right, text="上次开机 --", bg=CARD, fg=SUB, font=FONT_S, anchor=tk.E)
        self._sys_refs["boot_time"].pack(anchor=tk.E)
        self._sys_refs["os"] = tk.Label(
            right, text="系统 --", bg=CARD, fg=SUB, font=FONT_S, anchor=tk.E)
        self._sys_refs["os"].pack(anchor=tk.E)

        # ---- 五张状态卡：CPU / GPU / RAM / 网卡 / 主板 ----
        grid = tk.Frame(outer, bg=BG)
        grid.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1, uniform="st")
        self._build_status_card(grid, 0, 0, "CPU", "cpu")
        self._build_status_card(grid, 0, 1, "GPU", "gpu")
        self._build_status_card(grid, 0, 2, "RAM", "ram")
        self._build_status_card(grid, 1, 0, "网卡", "net")
        self._build_status_card(grid, 1, 1, "主板", "mb")

        # ---- 硬盘实时状态（一个硬盘一张卡）----
        self._sys_refs["disks"] = []
        if self.hardware.disks:
            sec = tk.Frame(outer, bg=BG)
            sec.pack(fill=tk.X, pady=(10, 0))
            tk.Label(sec, text="硬盘", bg=BG, fg=SUB, font=FONT_S,
                     anchor=tk.W).pack(fill=tk.X, pady=(0, 4))
            drow = tk.Frame(sec, bg=BG)
            drow.pack(fill=tk.X)
            for i, d in enumerate(self.hardware.disks):
                card = tk.Frame(drow, bg=CARD, highlightthickness=1,
                                highlightbackground=BORDER)
                card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
                tk.Label(card, text=d.model, bg=CARD, fg=TEXT, font=FONT_B,
                         anchor=tk.W, wraplength=300).pack(
                    fill=tk.X, padx=12, pady=(8, 0))
                size_txt = f"{d.interface} · {d.size_gb} GB" if d.size_gb else d.interface
                tk.Label(card, text=size_txt, bg=CARD, fg=SUB, font=FONT_S,
                         anchor=tk.W).pack(fill=tk.X, padx=12, pady=(0, 4))
                body = tk.Frame(card, bg=CARD)
                body.pack(fill=tk.X, padx=12, pady=(0, 2))
                tk.Label(body, text="使用", bg=CARD, fg=SUB, font=FONT_S,
                         width=5, anchor=tk.W).pack(side=tk.LEFT)
                refs = {}
                refs["used"] = tk.Label(body, text="--", bg=CARD, fg=TEXT,
                                        font=FONT_S, anchor=tk.W)
                refs["used"].pack(side=tk.LEFT, padx=(4, 8))
                refs["pct"] = tk.Label(body, text="", bg=CARD, fg=TEXT,
                                       font=FONT_S, anchor=tk.W)
                refs["pct"].pack(side=tk.RIGHT)
                refs["bar"] = tk.Canvas(card, height=8, bg=CARD,
                                        highlightthickness=0)
                refs["bar"].pack(fill=tk.X, padx=12, pady=(4, 0))
                refs["io"] = tk.Label(card, text="读取 -- · 写入 -- MB/s",
                                      bg=CARD, fg=SUB, font=FONT_S,
                                      anchor=tk.W)
                refs["io"].pack(fill=tk.X, padx=12, pady=(2, 8))
                refs["device"] = d.device_id
                self._sys_refs["disks"].append(refs)

        tk.Label(outer, text="共享显存、温度传感器待接入（LibreHardwareMonitor）",
                 bg=BG, fg=SUB, font=FONT_S, anchor=tk.W).pack(fill=tk.X, pady=(8, 0))

        # ---- 系统操作（移入系统状态页底部）----
        bottom = tk.Frame(outer, bg=BG)
        bottom.pack(fill=tk.X, pady=(8, 0))
        self._build_action_card(bottom)

        self._refresh_static_sys()

    def _refresh_static_sys(self):
        """填充硬件检测阶段已确定、无需每秒刷新的值（开机时间/虚拟化/主板）。"""
        s = self.hardware.system
        self._sys_refs["boot"].config(text=f"已运行 {s.uptime_text}")
        self._sys_refs["boot_time"].config(text=f"上次开机 {s.last_boot_text}")
        self._sys_refs["os"].config(text=f"{s.os_caption} · Build {s.os_build}")
        if "cpu" in self._sys_refs:
            self._sys_refs["cpu"]["virt"].config(
                text=self.hardware.cpu.virtualization)
        if "mb" in self._sys_refs:
            self._sys_refs["mb"]["name"].config(
                text=f"{self.hardware.motherboard.manufacturer} "
                     f"{self.hardware.motherboard.product}".strip())

    def _build_status_card(self, parent, row, col, title, key):
        """建一张「标题 + 若干 label:value 行」的状态卡，引用存进 self._sys_refs[key]。"""
        card = tk.Frame(parent, bg=CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        card.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
        tk.Label(card, text=title, bg=CARD, fg=TEXT, font=FONT_B,
                 anchor=tk.W).pack(fill=tk.X, padx=12, pady=(8, 2))
        refs = {}
        body = tk.Frame(card, bg=CARD)
        body.pack(fill=tk.X, padx=12, pady=(0, 8))

        def add(key, label):
            tk.Label(body, text=label, bg=CARD, fg=SUB, font=FONT_S,
                     anchor=tk.W, width=9).grid(sticky="w", pady=1)
            r = body.grid_size()[1] - 1
            v = tk.Label(body, text="--", bg=CARD, fg=TEXT, font=FONT_S,
                         anchor=tk.W)
            v.grid(row=r, column=1, sticky="w", pady=1)
            refs[key] = v

        if title == "CPU":
            for k, lab in [("freq", "目前频率"), ("util", "利用率"),
                           ("procs", "进程"), ("threads", "线程"),
                           ("handles", "句柄"), ("virt", "虚拟化")]:
                add(k, lab)
        elif title == "GPU":
            for k, lab in [("util", "利用率"), ("vram", "专用显存"),
                           ("shared", "共享显存"), ("temp", "温度")]:
                add(k, lab)
        elif title == "RAM":
            for k, lab in [("used", "使用量"), ("committed", "已提交"),
                           ("cached", "已缓存"), ("paged", "分页缓冲池"),
                           ("nonpaged", "非分页缓冲池")]:
                add(k, lab)
        elif title == "网卡":
            for k, lab in [("speed", "传输速度"), ("type", "连接类型"),
                           ("down", "实时接收"), ("up", "实时发送"),
                           ("signal", "信号强度")]:
                add(k, lab)
        elif title == "主板":
            for k, lab in [("name", "厂商/型号"), ("chip", "芯片组温度"),
                           ("status", "运行状态")]:
                add(k, lab)
        self._sys_refs[key] = refs

    # ================================================================
    # 每秒刷新
    # ================================================================
    def _tick(self):
        try:
            snap = self.monitor.latest
            if snap is not None:
                if self._page == "sys":
                    self._update_sys_page(snap)
                elif self._page == "hw":
                    self._update_gpu_bar(snap)
            self._update_status(snap)
        except Exception as e:
            self.status_label.config(text=f"渲染异常: {e}")
        finally:
            self.root.after(1000, self._tick)

    def _update_sys_page(self, snap):
        cpu = self._sys_refs["cpu"]
        cpu["freq"].config(
            text=f"{snap.cpu_freq_mhz:.0f} MHz" if snap.cpu_freq_mhz else "--")
        cpu["util"].config(text=f"{snap.cpu_percent:.1f}%",
                           fg=_pct_color(snap.cpu_percent))
        cpu["procs"].config(text=str(snap.proc_count))
        cpu["threads"].config(text=str(snap.thread_count))
        cpu["handles"].config(text=f"{snap.handle_count:,}")

        gpu = self._sys_refs["gpu"]
        if snap.gpu_percent is not None:
            gpu["util"].config(text=f"{snap.gpu_percent:.0f}%",
                               fg=_pct_color(snap.gpu_percent))
            gpu["vram"].config(
                text=f"{snap.gpu_mem_used_mb:.0f} / {snap.gpu_mem_total_mb:.0f} MB")
        else:
            gpu["util"].config(text="--", fg=SUB)
            gpu["vram"].config(text="无 NVIDIA 独显数据")
        gpu["shared"].config(text="待接入")
        gpu["temp"].config(text="待接入")

        ram = self._sys_refs["ram"]
        ram["used"].config(
            text=f"{snap.mem_used_gb:.1f} / {snap.mem_total_gb:.1f} GB")
        ram["committed"].config(
            text=f"{snap.ram_committed_gb:.1f} GB"
            if snap.ram_committed_gb is not None else "--")
        ram["cached"].config(
            text=f"{snap.ram_cached_gb:.1f} GB"
            if snap.ram_cached_gb is not None else "--")
        ram["paged"].config(
            text=f"{snap.ram_paged_pool_mb:.0f} MB"
            if snap.ram_paged_pool_mb is not None else "--")
        ram["nonpaged"].config(
            text=f"{snap.ram_nonpaged_pool_mb:.0f} MB"
            if snap.ram_nonpaged_pool_mb is not None else "--")

        net = self._sys_refs["net"]
        net["speed"].config(
            text=f"{snap.net_speed_mbps:.0f} Mbps" if snap.net_speed_mbps else "--")
        net["type"].config(text=snap.net_type)
        net["down"].config(text=f"{snap.net_down_mbps:.2f} MB/s")
        net["up"].config(text=f"{snap.net_up_mbps:.2f} MB/s")
        if snap.wifi_signal is not None:
            net["signal"].config(text=f"{snap.wifi_signal}%",
                                 fg=_pct_color(snap.wifi_signal))
        else:
            net["signal"].config(text="--")

        mb = self._sys_refs["mb"]
        mb["chip"].config(text="待接入")
        mb["status"].config(text="● 正常", fg=OK)

        # 硬盘卡（按 device_id 对齐硬件信息与实时统计）
        stat_map = {st.device_id: st for st in snap.disk_stats}
        for refs in self._sys_refs.get("disks", []):
            st = stat_map.get(refs["device"])
            if st is None:
                refs["used"].config(text="--")
                refs["pct"].config(text="")
                refs["io"].config(text="读取 -- · 写入 -- MB/s")
                refs["bar"].delete("all")
                continue
            if st.percent is not None:
                refs["used"].config(
                    text=f"已用 {st.used_gb:.1f} / {st.size_gb:.1f} GB")
                refs["pct"].config(text=f"{st.percent:.0f}%",
                                   fg=_pct_color(st.percent))
                self._draw_bar(refs["bar"], st.percent, _pct_color(st.percent))
            else:
                refs["used"].config(text="无挂载分区")
                refs["pct"].config(text="")
                refs["bar"].delete("all")
            refs["io"].config(
                text=f"读取 {st.read_mbps:.2f} · 写入 {st.write_mbps:.2f} MB/s")

    def _draw_bar(self, canvas, percent, color):
        canvas.delete("all")
        w = max(canvas.winfo_width(), 20)
        canvas.create_rectangle(0, 0, w, 8, fill="#E9EDF2", outline="")
        fw = max(2, int(w * min(100, percent) / 100))
        canvas.create_rectangle(0, 0, fw, 8, fill=color, outline="")

    def _update_gpu_bar(self, snap):
        refs = self._gpu_bar_refs
        if snap.gpu_percent is None:
            refs["util"].config(text="--%", fg=SUB)
            refs["vram"].config(text="无 NVIDIA 独显数据")
            refs["bar"].delete("all")
            return
        refs["util"].config(text=f"{snap.gpu_percent:.0f}%",
                            fg=_pct_color(snap.gpu_percent))
        refs["vram"].config(
            text=f"专用显存 {snap.gpu_mem_used_mb:.0f} / {snap.gpu_mem_total_mb:.0f} MB")
        pct = (snap.gpu_mem_used_mb / snap.gpu_mem_total_mb * 100
               if snap.gpu_mem_total_mb else 0)
        self._draw_bar(refs["bar"], pct, ACCENT)

    def _update_status(self, snap):
        if snap is None:
            return
        t = time.strftime("%H:%M:%S", time.localtime(snap.ts))
        state = "已暂停" if self._paused else "采集中"
        err = f"  |  采集异常: {self.monitor.last_error}" if self.monitor.last_error else ""
        self.status_label.config(
            text=f"最近更新 {t} · {state} · 已采样 {len(self.monitor.history)} 帧 "
                 f"（每 1 秒一帧，保留 60 帧）{err}")

    # ================================================================
    # 按钮动作
    # ================================================================
    def _refresh_hardware(self):
        def job():
            try:
                from modules.system_monitor.hardware_info import collect_hardware_info
                new_hw = collect_hardware_info()
                self.root.after(0, lambda: self._apply_hardware(new_hw))
            except Exception as e:
                self.root.after(0, lambda: self.status_label.config(
                    text=f"刷新失败: {e}"))

        import threading
        threading.Thread(target=job, daemon=True).start()
        self.status_label.config(text="正在刷新硬件信息…")

    def _apply_hardware(self, new_hw):
        self.hardware = new_hw
        self._update_sidebar_status()
        self._show_page(self._page)  # 重建当前页
        self.status_label.config(text="硬件信息已刷新")

    def _copy_report(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.hardware.summary())
        self.status_label.config(text="硬件报告已复制到剪贴板")

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.monitor.pause()
            self.pause_btn.config(text="继续监控")
        else:
            self.monitor.resume()
            self.pause_btn.config(text="暂停监控")

    def _run_selftest(self):
        """打开一个新的控制台窗口运行数据层自检（带 pause 保持显示）。"""
        import os
        import sys
        if getattr(sys, "frozen", False):
            # exe 打包版没有源码目录里的自检脚本
            messagebox.showinfo(
                "运行自检",
                "自检脚本不随 exe 打包。\n请在源码目录运行「运行自检.bat」或 python self_test.py。")
            return
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))  # ui.py → system_monitor → modules → 项目根
        try:
            subprocess.Popen(["cmd", "/c", "start", "", "运行自检.bat"],
                             cwd=root_dir)
        except Exception as e:
            self.status_label.config(text=f"无法启动自检: {e}")

    # ---------------- 系统操作 ----------------
    def _action_lock(self):
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"],
                       creationflags=CREATE_NO_WINDOW)

    def _action_sleep(self):
        if messagebox.askyesno("睡眠", "确定让电脑进入睡眠吗？"):
            subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState",
                            "0,1,0"], creationflags=CREATE_NO_WINDOW)

    def _action_restart(self):
        if messagebox.askyesno("重启", "确定要重启电脑吗？3 秒后执行。"):
            subprocess.run(["shutdown", "/r", "/t", "3"],
                           creationflags=CREATE_NO_WINDOW)

    def _action_shutdown(self):
        if messagebox.askyesno("关机", "确定要关机吗？3 秒后执行。"):
            subprocess.run(["shutdown", "/s", "/t", "3"],
                           creationflags=CREATE_NO_WINDOW)

    # ================================================================
    # 关闭
    # ================================================================
    def _on_close(self):
        try:
            self.monitor.stop()
        finally:
            self.root.destroy()
