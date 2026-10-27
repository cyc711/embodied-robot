"""
Webots 控制器（在本机、装好 Webots 后使用）
==========================================
- 完全自包含：感知/决策逻辑内联，不依赖项目其他文件夹，放在任意控制器目录都能直接运行。
- 设备发现：用 Node 节点类型常量正确识别（v2 修复：getNodeType 返回整数而非字符串），
  并带 getDevice 名称兜底；无需 GPS/Compass，用轮编码器/位置传感器做里程计。
- 感知：摄像头实时找"红色块"（颜色阈值，无需 YOLO），做出
  PATROL -> INVESTIGATE(视觉伺服靠近) -> ALERT(停车告警) 的具身闭环。
Webots 的 Python API 通过 `controller` 包提供，沙箱/无 GUI 环境无法运行。
"""
import sys
import os
import json
import math
import urllib.request
import urllib.error

try:
    from controller import Robot, Camera, Motor, GPS, Compass, Node
except ImportError:
    sys.stderr.write("本控制器只能在 Webots 内运行（需要 Webots 的 controller 包）。\n")
    raise

TIME_STEP = 64
MAX_SPEED = 6.28
# 巡逻点用坐标(米)，按你场景实际位置调整
PATROL = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
# Pioneer3DX 几何参数（若实测漂移，微调这两个值即可）
WHEEL_RADIUS = 0.0975   # 轮半径(米)
WHEELBASE = 0.331       # 轮距(米)
# ---- 感知/决策参数（可视情况微调） ----
RED_AREA_ALERT = 0.079  # 红色块占画面比例达到此值=已"紧贴抵近"，才停车告警
                       # （门槛 0.079：机器人须开到几乎贴脸才停，贴得最紧；
                       #  红块极限占比约 0.15，0.079 仍可达但余量极小）
INVESTIGATE_TIMEOUT = 800  # 持续核实这么久仍未抵近(多为误检)，放弃并回巡逻
ALERT_HOLD = 80         # 告警后原地停留步数（约 80*64ms≈5s）
ALERT_COOLDOWN = 300    # 告警后忽略红块、继续巡逻的冷却步数（避免反复触发）


# ---------- 内联：具身决策状态机（巡逻 + 异常核实闭环） ----------
class State:
    PATROL = "PATROL"
    INVESTIGATE = "INVESTIGATE"
    ALERT = "ALERT"


class RobotBrain:
    def __init__(self, patrol):
        self.patrol = patrol
        self.pi = 0
        self.state = State.PATROL
        self.alert_count = 0
        self.alert_timer = 0
        self.cooldown = 0
        self.inv_count = 0      # 连续核实帧计数（用于"持续抵近"判定，过滤瞬时误检）
        self.ban = 0            # 核查禁令步数（超时放弃后短暂不再核查，防"看到→超时"死循环）

    def step(self, detections):
        # 冷却中：忽略一切检测，继续巡逻
        if self.cooldown > 0:
            self.cooldown -= 1
            return State.PATROL

        # 核查禁令期：刚才核实过但没抵近，先专心巡逻一圈再理睬红色信号
        if self.ban > 0:
            self.ban -= 1
            return State.PATROL

        # 告警持后期：原地停留，结束后进入冷却
        if self.state == State.ALERT:
            self.alert_timer -= 1
            if self.alert_timer <= 0:
                self.state = State.PATROL
                self.cooldown = ALERT_COOLDOWN
            return self.state

        if detections:
            d = detections[0]
            self.inv_count += 1
            # 抵近闸门：必须"红色占比足够大(已开到跟前)"且"连续多帧确认"，才停车告警
            reached = (d.get("area", 0.0) >= RED_AREA_ALERT) and (self.inv_count >= 3)
            if reached:
                self.state = State.ALERT
                self.alert_count += 1
                self.alert_timer = ALERT_HOLD
                self.inv_count = 0
            elif self.inv_count > INVESTIGATE_TIMEOUT:
                # 长时间核实无果（多为自身红部件/地砖误检），放弃回到巡逻，
                # 并设置核查禁令，避免"看到→核实→超时"原地循环
                self.inv_count = 0
                self.ban = 300
                self.state = State.PATROL
            else:
                # 发现红色但不算足够近 → 驱车抵近核实（视觉伺服推进）
                self.state = State.INVESTIGATE
        else:
            self.inv_count = 0
            self.state = State.PATROL
        return self.state


# ---------- 内联：具身语义层（把"红色异常"映射为自然语言告警，可选接 LLM） ----------
class SemanticLayer:
    """
    具身智能的"高层语义决策"：把底层感知的结构化结果（发现红色异常、面积、坐标、次数）
    翻译成面向人或物业系统的自然语言研判，例如"疑似老人跌倒，建议派人核实"。
    这是本项目"AI+养老"叙事的核心——机器人不只是停下，还能"理解"异常并生成可执行告警。

    工程上为保证单人作品稳健可演示：
      - 默认使用【本地规则模板】生成自然语言，零配置、零网络、必定能跑；
      - 若设置了环境变量 LLM_API_KEY，则改为调用 OpenAI 兼容接口
        （DeepSeek / 通义 / 智谱 等均可，设 LLM_BASE_URL、LLM_MODEL 切换），
        由大模型生成更自然的研判文案；
      - 调用失败 / 超时（4s）/ 无网络，自动降级回本地模板，绝不抛异常影响机器人运动。
    """
    def __init__(self):
        self.api_key = os.environ.get("LLM_API_KEY", "").strip()
        self.base_url = os.environ.get("LLM_BASE_URL",
                                       "https://api.deepseek.com/v1/chat/completions").strip()
        self.model = os.environ.get("LLM_MODEL", "deepseek-chat").strip()
        self.use_llm = bool(self.api_key)
        self.last_source = "本地规则模板" if not self.use_llm else f"大模型({self.model})"

    def interpret(self, area, pos, alert_count):
        """返回一句自然语言告警。area=红块占比; pos=(x,y); alert_count=累计次数。"""
        x = round(pos[0], 2) if pos else 0.0
        y = round(pos[1], 2) if pos else 0.0
        if self.use_llm:
            try:
                return self._call_llm(area, x, y, alert_count)
            except Exception as e:
                sys.stderr.write(f"[语义] LLM 调用失败，降级本地模板: {e}\n")
                self.last_source = "本地规则模板(LLM失败降级)"
                return self._local(area, x, y, alert_count)
        return self._local(area, x, y, alert_count)

    def _local(self, area, x, y, alert_count):
        # 本地规则模板：面积越大=离异常越近，给出分级研判（不依赖网络）
        if area >= 0.06:
            level, desc = "高置信", "疑似老人跌倒或突发异常（已贴近确认红色标记）"
        else:
            level, desc = "中置信", "发现可疑红色异常标记，需进一步确认"
        return (f"语义研判[{level}]：巡检机器人在社区坐标({x}, {y}){desc}，"
                f"建议物业/家属立即派人现场核实。（第{alert_count}次告警）")

    def _call_llm(self, area, x, y, alert_count):
        prompt = (
            f"你是社区养老巡检机器人的高层语义决策模块。底层视觉在坐标({x}, {y})"
            f"检测到红色异常标记，面积占比{area:.3f}（越大表示越贴近确认），"
            "这是社区独居老人突发状况（如跌倒、燃气泄漏、入侵）的代理信号。"
            "请用一句不超过40字的中文，把该信号转化为面向物业/家属的自然语言告警，"
            "语气专业、可执行，例如：'疑似老人跌倒，建议立即派人现场核实'。"
            "只返回这句告警文案，不要任何解释。"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": "你是社区养老具身巡检机器人的语义决策助手，输出简洁专业。"},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 64,
            "temperature": 0.3,
        }
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return "语义研判[大模型]：" + data["choices"][0]["message"]["content"].strip()


# ---------- 内联：感知模块（摄像头红色块检测，可升级为 YOLO） ----------
class Detector:
    def __init__(self, camera, sample=4):
        self.camera = camera
        self.sample = sample  # 每 sample 像素采一次样，降算力

    def detect(self):
        """
        返回 [{"cls":"fall","cx":-1..1(画面水平中心,右为正),"area":占比}, ...]
        无红块返回空列表。颜色阈值法，无需模型。
        v2.5 修复：
        - 不调用 camera.getImageArray()（部分版本内部有 bug 会崩溃）
        - 不导入 imageGetRed 等辅助函数（部分版本未导出会 ImportError）
        改为直接读 getImage() 原始字节。Webots 图像为 BGRA 排列、按行存储：
        像素(x,y) 的第 i = (y*宽 + x)*4 字节起，B/G/R/A 依次各 1 字节。
        这是所有 Webots 版本通用的最底层读法。
        """
        if not self.camera:
            return []
        raw = self.camera.getImage()
        if not raw:
            return []
        h = self.camera.getHeight()
        w = self.camera.getWidth()
        s = max(1, self.sample)
        # v2.11：跳过图像底部 10%——机器人自身红色机身常出现在镜头最下方，
        # 不扫描这一带可消除"起点原地误警"（仅裁 10%，避免误伤靠近时的红块）。
        y_end = int(h * 0.90)
        red_px = 0
        sum_x = 0
        total = 0
        for y in range(0, y_end, s):
            row = y * w * 4
            for x in range(0, w, s):
                i = row + x * 4
                b = raw[i]
                g = raw[i + 1]
                r = raw[i + 2]
                # 颜色阈值（与已验证可检测版本一致）：识别饱和红
                if r > 140 and r > g + 50 and r > b + 50:
                    red_px += 1
                    sum_x += x
                total += 1
        if red_px < 25:           # 噪声过滤（弱红信号将被忽略）
            return []
        area = red_px / total
        cx = (sum_x / red_px - w / 2.0) / (w / 2.0)   # 归一化到 [-1,1]
        return [{"cls": "fall", "cx": cx, "area": area}]


# ---------- 设备发现（v2：用 Node 类型常量 + 名称兜底） ----------
def discover_devices(robot):
    camera = left = right = gps = compass = ps_left = ps_right = None
    names = set()                    # 已存在的设备名集合（避免 getDevice 触发警告）
    n = robot.getNumberOfDevices()
    for i in range(n):
        d = robot.getDeviceByIndex(i)
        name = (d.getName() or "").lower()
        names.add(name)
        t = d.getNodeType()          # 返回 int（v1 误按字符串比较导致全漏）
        if t == Node.CAMERA:
            camera = d
        elif t == Node.GPS:
            gps = d
        elif t == Node.COMPASS:
            compass = d
        elif t in (Node.ROTATIONAL_MOTOR, Node.LINEAR_MOTOR):
            if "left" in name:
                left = d
            elif "right" in name:
                right = d
        elif t == Node.POSITION_SENSOR:
            if "left" in name:
                ps_left = d
            elif "right" in name:
                ps_right = d

    # 名称兜底（仅当设备名确实存在时才调用 getDevice，避免 Webots 打印 "not found" 警告）
    def try_get(name):
        if name not in names:
            return None
        try:
            return robot.getDevice(name)
        except Exception:
            return None

    if camera is None:
        camera = try_get("camera")
    if left is None:
        left = try_get("left wheel motor")
    if right is None:
        right = try_get("right wheel motor")
    if ps_left is None:
        ps_left = try_get("left wheel sensor")
    if ps_right is None:
        ps_right = try_get("right wheel sensor")
    if gps is None:
        gps = try_get("gps")
    if compass is None:
        compass = try_get("compass")
    return camera, left, right, gps, compass, ps_left, ps_right


def main():
    robot = Robot()
    (camera, left, right, gps, compass,
     ps_left, ps_right) = discover_devices(robot)

    if camera:
        camera.enable(TIME_STEP)
    for m in (left, right):
        if m:
            m.setPosition(float("inf"))
            m.setVelocity(0.0)
    if gps:
        gps.enable(TIME_STEP)
    if compass:
        compass.enable(TIME_STEP)
    for ps in (ps_left, ps_right):
        if ps:
            ps.enable(TIME_STEP)

    brain = RobotBrain(PATROL)
    detector = Detector(camera)
    semantic = SemanticLayer()   # 具身语义层：把结构化告警翻译为自然语言研判（可接 LLM）

    # ---- 里程计状态（优先用位置传感器，否则用电机读数） ----
    # v2.9 修复：不能在第一次 step 之前读传感器——Webots 首读可能返回 NaN，
    # 一旦基准被污染，位置永远=(nan,nan)，机器人将永不停车、直线冲出。
    def wheel_pos(side):
        ps = ps_left if side == "l" else ps_right
        m = left if side == "l" else right
        if ps:
            return ps.getValue()
        if m:
            return m.getPosition()
        return 0.0

    prev_l = None     # None = 尚未建立基准（首步只记录、不积分）
    prev_r = None
    x = z = theta = 0.0

    def update_odometry():
        nonlocal x, z, theta, prev_l, prev_r
        if not (left and right):
            return (x, z)
        pl, pr = wheel_pos("l"), wheel_pos("r")
        if prev_l is None or prev_r is None:
            prev_l, prev_r = pl, pr          # 首步：仅建立基准
            return (x, z)
        if not (math.isfinite(pl) and math.isfinite(pr)):
            # 传感器异常读数：重置基准并跳过本帧，绝不污染位置
            prev_l = pl if math.isfinite(pl) else 0.0
            prev_r = pr if math.isfinite(pr) else 0.0
            return (x, z)
        dl = (pl - prev_l) * WHEEL_RADIUS
        dr = (pr - prev_r) * WHEEL_RADIUS
        prev_l, prev_r = pl, pr
        dc = (dl + dr) / 2.0          # 中心前进距离
        dth = (dr - dl) / WHEELBASE   # 朝向变化
        theta += dth
        x += dc * math.cos(theta)
        z += dc * math.sin(theta)
        if not (math.isfinite(x) and math.isfinite(z) and math.isfinite(theta)):
            x = z = theta = 0.0       # 兜底自愈：异常时归零重来
        return (x, z)

    def get_pos():
        if gps:
            v = gps.getValues()
            return (v[0], v[1])          # Webots 是 z 轴朝上，地面平面为 (x, y)
        return (x, z)

    def get_heading():
        if compass:
            v = compass.getValues()
            return math.atan2(v[1], v[0])  # z-up: 水平面是 x-y 平面
        return theta

    def stop():
        if left and right:
            left.setVelocity(0.0)
            right.setVelocity(0.0)

    def steer_to(target, pos, heading, speed=0.5):
        if not (left and right):
            return False
        # NaN 防护：位置或朝向异常时停车等待下一帧，绝不带着脏数据导航
        if not (math.isfinite(pos[0]) and math.isfinite(pos[1])
                and math.isfinite(heading)):
            stop()
            return False
        dx = target[0] - pos[0]
        dy = target[1] - pos[1]
        dist = math.hypot(dx, dy)
        if dist < 0.25:
            stop()
            return True
        desired = math.atan2(dy, dx)
        err = desired - heading
        while err > math.pi:
            err -= 2 * math.pi
        while err < -math.pi:
            err += 2 * math.pi
        if abs(err) > 0.2:
            left.setVelocity(-MAX_SPEED * 0.5)
            right.setVelocity(MAX_SPEED * 0.5)
        else:
            left.setVelocity(MAX_SPEED * speed)
            right.setVelocity(MAX_SPEED * speed)
        return False

    def servo_to_red(cx, area=0.0):
        """朝红色块方向转向并快速逼近（视觉伺服）。目标：让机器人"紧贴"红块后停车告警。
        v2.17 提速：把前进系数大幅抬高（之前系数上限仅 0.225，实际线速度≈0.14 m/s，
        远慢于巡逻直行）。现远处逼近线速度≈0.3 m/s（接近巡逻上限），贴前也明显加快；
        同时保留"贴近自动减速"(gap→0 时 forward 趋近下限)防冲过。
        """
        if not (left and right):
            return
        gap = max(0.0, RED_AREA_ALERT - area)
        forward = MAX_SPEED * max(0.15, 6.0 * gap)      # 远处快速逼近，贴前自动减速(底速提高)
        turn_gain = 1.0 if gap > 0.02 else max(0.4, 80.0 * gap)  # 远处全速对准，贴时轻转
        turn = cx * MAX_SPEED * turn_gain
        left.setVelocity(forward + turn)
        right.setVelocity(forward - turn)

    print(f"[版本 v2.20] 控制器文件路径: {__file__}")
    print("Webots 具身巡检控制器启动：开始巡逻（编码器里程计 + 红色异常检测 + 语义研判层）")
    print(f"[设备] camera={'Y' if camera else 'N'} left={'Y' if left else 'N'} "
          f"right={'Y' if right else 'N'} gps={'Y' if gps else 'N'} compass={'Y' if compass else 'N'} "
          f"编码器={'Y' if (ps_left and ps_right) else 'N'}")
    if not (left and right):
        print("[警告] 未发现左右轮电机，机器人无法移动！请确认场景里是 Pioneer3DX。")
    print(f"[语义层] {'已启用大模型：' + semantic.model if semantic.use_llm else '本地规则模板（未配置 LLM_API_KEY，零网络运行；设置后切换真大模型）'}")

    stuck = 0    # 连续未到达当前巡逻点的步数（防里程计漂移导致原地转向卡死）
    tick = 0      # 全局步数（用于日志抽样，避免控制台刷屏）
    prev_state = None
    while robot.step(TIME_STEP) != -1:
        update_odometry()
        pos = get_pos()
        heading = get_heading()
        try:
            detections = detector.detect()
        except Exception as e:          # 感知层任何异常只跳过本帧，绝不崩溃
            sys.stderr.write(f"[感知警告] 本帧检测失败已跳过: {e}\n")
            detections = []
        state = brain.step(detections)
        tick += 1

        if state == State.PATROL:
            target = PATROL[brain.pi]
            if steer_to(target, pos, heading):
                brain.pi = (brain.pi + 1) % len(PATROL)
                stuck = 0
                print(f"[PATROL] 到达巡逻点 {target}，下一个目标: {PATROL[brain.pi]}")
            else:
                stuck += 1
                if stuck > 500:   # 约32秒仍未到达：多半是里程计漂移，跳下一个巡逻点
                    stuck = 0
                    brain.pi = (brain.pi + 1) % len(PATROL)
                    print(f"[PATROL] 目标 {target} 长时间未到达(可能里程计漂移)，"
                          f"跳到下一个巡逻点 {PATROL[brain.pi]}")
        elif state == State.INVESTIGATE:
            servo_to_red(detections[0]["cx"], detections[0]["area"])
            d = detections[0]
            side = f"右{d['cx']:.2f}" if d["cx"] >= 0 else f"左{-d['cx']:.2f}"
            if prev_state != State.INVESTIGATE:
                # 进入核实：只打印一次入口信息
                print(f"[INVESTIGATE] 发现红色异常@方位{side}，面积{d['area']:.3f}，"
                      f"目标紧贴(门槛{RED_AREA_ALERT:.3f})，开始逼近")
            elif tick % 20 == 0:
                # 过程抽样：每 20 步汇报一次，避免控制台刷屏
                print(f"[INVESTIGATE] 逼近中… 方位{side}，面积{d['area']:.3f}")
        elif state == State.ALERT:
            stop()
            if brain.alert_timer == ALERT_HOLD:
                print(f"[ALERT] ⚠ 已抵近异常并触发告警！（累计告警 {brain.alert_count} 次，"
                      f"位置≈{tuple(round(v, 2) for v in pos)}）")
                # 语义层：把结构化告警翻译为自然语言研判（默认本地模板，配 LLM_API_KEY 走真大模型）
                area_now = detections[0]["area"] if detections else 0.0
                verdict = semantic.interpret(area_now, pos, brain.alert_count)
                print(f"[语义告警] {verdict}")
                print(f"[语义告警] 研判来源：{semantic.last_source}")
            elif tick % 10 == 0 and brain.alert_timer > 0:
                print(f"[ALERT] 告警处置中… 剩余 {brain.alert_timer} 步后继续巡逻")
        prev_state = state


if __name__ == "__main__":
    main()
