"""
感知模块：异常检测
- 无头仿真模式：基于世界真值 + 相机可视范围（distance < range）模拟"摄像头看到异常"
- 真实机器人模式：把 detect() 换成 YOLO/视觉大模型对 camera_frame 的推理
"""
try:
    from ultralytics import YOLO
    _YOLO_OK = True
except Exception:
    _YOLO_OK = False


class Detector:
    def __init__(self, use_yolo=False, model_path="yolov8n.pt", cam_range=6):
        self.use_yolo = use_yolo and _YOLO_OK
        self.cam_range = cam_range
        self.model = None
        if self.use_yolo:
            self.model = YOLO(model_path)

    def detect(self, camera_frame, robot_pos, world):
        """
        camera_frame: 真实模式下为图像数组；无头模式可传 None
        返回 detections: list[{"type","pos","distance"}]
        """
        if self.use_yolo and camera_frame is not None:
            # === 真实模式：用 YOLO 推理 camera_frame ===
            results = self.model(camera_frame, verbose=False)
            # TODO: 把 results 映射为 {type, pos, distance}（需结合深度/定位）
            return self._parse_yolo(results, robot_pos)

        # === 无头仿真模式：基于世界真值 + 可视范围 ===
        detections = []
        rx, ry = robot_pos
        for a in world.active_anomalies():
            ax, ay = a.pos
            d = ((ax - rx) ** 2 + (ay - ry) ** 2) ** 0.5
            if d <= self.cam_range:
                detections.append({"type": a.atype, "pos": a.pos, "distance": round(d, 2)})
        return detections

    def _parse_yolo(self, results, robot_pos):
        # 预留：把 YOLO 结果转成统一格式
        return []
