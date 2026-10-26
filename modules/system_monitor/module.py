# -*- coding: utf-8 -*-
"""
系统检测模块（实现 BaseModule 生命周期接口）。

initialize：采集硬件信息 + 启动资源监控后台线程
start：      打开 tkinter 仪表盘并进入主循环
stop：       停止监控线程（关窗时由 ui 的 WM_DELETE_WINDOW 触发）
"""
from core.base_module import BaseModule


class SystemMonitorModule(BaseModule):
    name = "系统检测"

    def initialize(self) -> None:
        from modules.system_monitor.hardware_info import collect_hardware_info
        from modules.system_monitor.resource_monitor import ResourceMonitor
        # 1) 硬件信息：一次性采集（WMI 首次连接较慢，属正常）
        self.hardware = collect_hardware_info()
        # 2) 资源监控：后台线程每秒采集
        self.monitor = ResourceMonitor(interval=1.0, history=60)
        self.monitor.start()

    def start(self) -> None:
        import tkinter as tk
        from modules.system_monitor.ui import SystemMonitorUI
        root = tk.Tk()
        self.ui = SystemMonitorUI(root, self.monitor, self.hardware)
        root.mainloop()

    def stop(self) -> None:
        if getattr(self, "monitor", None) is not None:
            self.monitor.stop()
