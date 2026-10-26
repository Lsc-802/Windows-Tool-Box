# -*- coding: utf-8 -*-
"""
界面冒烟测试 —— 打开仪表盘渲染若干秒后自动关闭。

用途：不依赖人工观察，验证 UI 构建 + 每帧渲染是否有运行时异常。
正常输出：SMOKE OK
"""
import sys
import tkinter as tk


def main() -> int:
    from modules.system_monitor.module import SystemMonitorModule
    from modules.system_monitor.ui import SystemMonitorUI

    module = SystemMonitorModule()
    module.initialize()

    root = tk.Tk()
    SystemMonitorUI(root, module.monitor, module.hardware)

    def close():
        print("SMOKE OK: 界面构建与渲染正常")
        module.stop()
        root.destroy()

    # 渲染 3 秒（3 次刷新周期）后自动关闭
    root.after(3500, close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
