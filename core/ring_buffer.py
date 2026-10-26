# -*- coding: utf-8 -*-
"""
环形缓冲 —— 存放最近 N 帧资源快照。

设计逻辑：
资源监控每秒产生一帧快照，界面要画「最近 1 分钟的趋势曲线」。
如果用普通列表，就得不停地 pop(0) 挪位，效率低；
deque(maxlen=60) 满了之后自动丢弃最旧的一帧，天然形成环形缓冲。
"""
from collections import deque
from typing import List, Any, Optional


class RingBuffer:
    def __init__(self, capacity: int = 60):
        self._buf: deque = deque(maxlen=max(1, capacity))

    def push(self, item: Any) -> None:
        """写入一帧；超出容量时自动淘汰最旧帧。"""
        self._buf.append(item)

    def to_list(self) -> List[Any]:
        """按时间从旧到新返回全部帧（供画曲线用）。"""
        return list(self._buf)

    @property
    def latest(self) -> Optional[Any]:
        """最新一帧；缓冲为空时返回 None。"""
        return self._buf[-1] if self._buf else None

    def __len__(self) -> int:
        return len(self._buf)
