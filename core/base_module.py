# -*- coding: utf-8 -*-
"""
模块基类 —— 所有功能模块的统一接口。

设计逻辑：
主框架不关心某个模块内部怎么实现（弹窗拦截、垃圾清理、系统检测……），
只通过 initialize / start / stop 三个生命周期方法调度它。
这样后续每加一个新功能，只需新建一个继承 BaseModule 的类并注册进来，
不影响其他模块，做到「高内聚、低耦合」。
"""
from abc import ABC, abstractmethod


class BaseModule(ABC):
    """功能模块基类。"""

    # 模块显示名称，主框架用于展示（如「系统检测」「弹窗拦截」）
    name: str = "未命名模块"

    @abstractmethod
    def initialize(self) -> None:
        """模块初始化：准备数据、建立连接、启动后台线程等（不阻塞界面）。"""

    @abstractmethod
    def start(self) -> None:
        """模块启动：显示界面 / 进入主循环。"""

    @abstractmethod
    def stop(self) -> None:
        """模块停止：释放资源、停止后台线程，保证可重复启停。"""
