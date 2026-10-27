"""
决策模块：具身智能核心 —— 感知→决策→行动的闭环状态机
状态：PATROL(巡逻) → INVESTIGATE(前往核实) → ALERT(告警+陪护) → 回到 PATROL
真实部署时，INVESTIGATE 的"决策"可由大模型/VLA 替代规则（见注释）。
"""
from enum import Enum


class State(Enum):
    PATROL = "PATROL"
    INVESTIGATE = "INVESTIGATE"
    ALERT = "ALERT"


class RobotBrain:
    def __init__(self, patrol_points, alert_radius=1.5):
        self.state = State.PATROL
        self.patrol_points = patrol_points
        self.pi = 0
        self.target = None
        self.alert_count = 0
        self.alert_radius = alert_radius

    def step(self, robot_pos, detections):
        """
        输入：机器人位置、本轮感知结果
        输出：当前状态（并可能更新 target）
        """
        if detections:
            d = detections[0]
            self.target = d["pos"]
            # 若已足够近 → 触发告警；否则前往核实
            if d["distance"] <= self.alert_radius:
                if self.state != State.ALERT:
                    self.alert_count += 1
                self.state = State.ALERT
            else:
                self.state = State.INVESTIGATE
        else:
            if self.state == State.ALERT:
                # 异常已处置，恢复巡逻
                self.state = State.PATROL
                self.target = None
            elif self.state == State.INVESTIGATE:
                # 没看到异常了且已抵达目标点 → 视为处置完成
                if robot_pos == self.target:
                    self.alert_count += 1
                    self.state = State.ALERT
        return self.state

    def next_patrol_point(self):
        p = self.patrol_points[self.pi]
        self.pi = (self.pi + 1) % len(self.patrol_points)
        return p
