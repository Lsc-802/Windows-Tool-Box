# -*- coding: utf-8 -*-
"""
Windows Tool Box 测试版 · 程序入口

启动方式（推荐）：
    双击「启动测试版.vbs」——无任何控制台窗口闪现；
    或双击「启动测试版.bat」——会闪一下命令窗口（属 .bat 特性）；
    或直接运行本文件。

单实例保护：
    用 Windows 命名互斥体保证同时只有一个实例在运行。
    重复启动时，已有实例继续运行，新启动的进程会弹一个提示框后退出。

设计：
    主框架只负责创建并调度「系统检测」这一个模块；
    以后每增加一个功能模块，在这里按顺序注册即可。
"""
import ctypes
import os
import sys

# 命名互斥体：所有实例共用这个名字，系统保证同一时刻只有一个进程能创建成功
MUTEX_NAME = "Local\\WindowsToolBox_MainFrame"

if getattr(sys, "frozen", False):
    # PyInstaller windowed（无控制台）模式下 sys.stdout/stderr 为 None，
    # 直接 print() 会抛 AttributeError 导致程序秒退。重定向到空设备即可。
    for _stream in ("stdout", "stderr"):
        if getattr(sys, _stream) is None:
            setattr(sys, _stream, open(os.devnull, "w", encoding="utf-8"))


def _acquire_single_instance() -> bool:
    """通过 Windows 命名互斥体实现单实例保护。

    原理：CreateMutexW 创建一个「已存在则返回旧句柄」的互斥对象，
    第一次创建成功（GetLastError != ERROR_ALREADY_EXISTS），
    后续进程创建时返回 183 → 说明已有实例在运行。

    注意：返回 True 时必须保持句柄存活，否则互斥体被释放、保护失效。
    这里把句柄挂在模块全局变量上防 GC，进程退出时操作系统自动回收。
    """
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already_exists = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    if already_exists:
        kernel32.CloseHandle(handle)
        return False
    globals()["_mutex_handle"] = handle
    return True


def main() -> int:
    # 1) 单实例保护：已有实例在运行则提示后退出，不重复开窗
    if not _acquire_single_instance():
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "Windows Tool Box 已在运行。\n请查看桌面或任务栏上的现有窗口。",
                "Windows Tool Box", 0x40)  # 0x40 = 信息图标
        except Exception:
            pass
        return 0

    # 2) 图形界面依赖 tkinter；缺失时给出明确提示而不是静默失败
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("[错误] 当前 Python 缺少 tkinter 支持，无法打开界面。")
        print("       请使用 python.org 的完整版 Python，或运行 python self_test.py 做数据层自检。")
        return 1

    from modules.system_monitor.module import SystemMonitorModule

    module = SystemMonitorModule()
    print("[Windows Tool Box] 正在初始化「系统检测」模块…")
    module.initialize()
    print("[Windows Tool Box] 初始化完成，打开界面（关闭窗口即退出）。")
    try:
        module.start()
    except KeyboardInterrupt:
        pass
    finally:
        module.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
