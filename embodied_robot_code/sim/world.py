"""
社区世界（2D 网格仿真）
用于无头测试：提供巡逻点、异常事件、相机"可视范围"判定。
真实部署时这份逻辑由 Webots 场景 + 机器人传感器替代。
"""
from dataclasses import dataclass, field


@dataclass
class Anomaly:
    pos: tuple
    atype: str
    active: bool = True
    detected_step: int = None


class World:
    def __init__(self, width=20, height=20, patrol_points=None):
        self.width = width
        self.height = height
        self.patrol_points = patrol_points or [(2, 2), (18, 2), (18, 18), (2, 18)]
        self.anomalies: list = []
        self.step = 0

    def spawn_anomaly(self, pos, atype="fall"):
        self.anomalies.append(Anomaly(pos=pos, atype=atype))
        self.step += 1

    def active_anomalies(self):
        return [a for a in self.anomalies if a.active]
