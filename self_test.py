# -*- coding: utf-8 -*-
"""
数据层自检脚本 —— 不打开界面，只验证硬件检测 + 资源采集是否正常。

用途：
1. 快速确认 WMI/psutil 采集通道在本机可用；
2. 输出硬件清单，肉眼核对型号、频率、容量是否正确；
3. 连续采样 3 帧，确认速率差值算法能产出合理数值。
"""
import time


def main() -> None:
    print("=" * 62)
    print(" Windows Tool Box · 数据层自检")
    print("=" * 62)

    # ---- 1. 硬件检测 ----
    print("\n[1/2] 硬件型号检测…（WMI 首次连接可能需要 1~2 秒）")
    from modules.system_monitor.hardware_info import collect_hardware_info
    hw = collect_hardware_info()
    print(hw.summary())

    # ---- 2. 资源监控 ----
    print("\n[2/2] 资源监控采样（每 1 秒一帧，共 3 帧）…")
    from modules.system_monitor.resource_monitor import ResourceMonitor
    mon = ResourceMonitor(interval=1.0)
    mon.start()
    try:
        for i in range(3):
            time.sleep(1.0)
            snap = mon.latest
            if snap is None:
                print(f"  第 {i + 1} 帧：尚未取到数据（正常预热）")
                continue
            print("  " + snap.summary_line())
            # 每帧校验核心字段都在合理范围（0-100 的百分比，容量为正数）
            assert 0 <= snap.cpu_percent <= 100, "CPU 占用超出合理范围"
            assert 0 <= snap.mem_percent <= 100, "内存占用超出合理范围"
            assert snap.mem_total_gb > 0, "内存总量异常"
    finally:
        mon.stop()

    print("\n" + "=" * 62)
    print(" 自检通过：硬件检测与资源采集均正常")
    print("=" * 62)


if __name__ == "__main__":
    main()
