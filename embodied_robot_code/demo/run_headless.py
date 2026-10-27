"""
无头仿真主程序：把 World + Detector + RobotBrain 串成闭环并打印日志
不依赖 Webots / GPU，沙箱与本地均可直接运行，用于验证具身逻辑。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.world import World
from perception.detector import Detector
from decision.state_machine import RobotBrain, State


def move_toward(pos, target, step=1):
    x, y = pos
    tx, ty = target
    nx = x + (step if tx > x else -step if tx < x else 0)
    ny = y + (step if ty > y else -step if ty < y else 0)
    return (nx, ny)


def main(max_steps=45):
    world = World()
    detector = Detector()  # 无头模式（mock 感知）
    brain = RobotBrain(world.patrol_points)
    robot = (2, 2)

    print("=== 具身养老/社区巡检机器人 · 无头仿真演示 ===")
    print(f"巡逻点: {world.patrol_points} | 相机可视范围: {detector.cam_range}\n")

    for t in range(max_steps):
        # 第 12 步注入一个"走廊跌倒"事件，模拟社区异常（放在巡逻路径附近，确保相机可视范围能覆盖）
        if t == 12:
            world.spawn_anomaly((10, 2), "fall")
            print(f"[t={t:02d}] 世界事件: 社区走廊发现跌倒人员 @ (10,2)")

        detections = detector.detect(None, robot, world)
        state = brain.step(robot, detections)

        if state == State.PATROL:
            target = brain.patrol_points[brain.pi]
            if robot == target:
                target = brain.next_patrol_point()
            robot = move_toward(robot, target)
            act = f"巡逻中，前往巡逻点 {target}"

        elif state == State.INVESTIGATE:
            robot = move_toward(robot, brain.target)
            act = f"检测到异常[{detections[0]['type']}] @距离{detections[0]['distance']}，前往核实 {brain.target}"

        elif state == State.ALERT:
            act = f"⚠ 已靠近异常，触发告警 + 语音陪护（累计告警 {brain.alert_count}）"
            # 处置完成：标记异常已处理，回到巡逻
            for a in world.active_anomalies():
                if a.pos == brain.target:
                    a.active = False
            brain.state = State.PATROL
            brain.target = None

        print(f"[t={t:02d}] 位置{robot} | {state.value:11s} | {act}")

    print(f"\n演示结束。共触发告警: {brain.alert_count} 次；剩余未处理异常: {len(world.active_anomalies())}")


if __name__ == "__main__":
    main()
