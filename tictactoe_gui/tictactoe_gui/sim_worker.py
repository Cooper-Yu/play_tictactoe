"""Connect the tablet's serialized jobs to the existing Gazebo motion driver."""
import copy
import json
import math
import queue
import time
from pathlib import Path


def simulation_worker(session, *, fast_game=False, perception=None):
    """! @brief Run ROS on one worker; accept stop requests during every spin cycle.

    The first GUI deliberately requires the validated simulation profile.
    It cannot dispatch hardware commands. A stopped/failed path is never
    automatically resumed; every new drawing is a fresh explicit job.
    """
    import cv2
    from ament_index_python.packages import get_package_share_directory
    from cv_bridge import CvBridge, CvBridgeError
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    import yaml
    from tictactoe_motion.board_canvas import BoardCanvas
    from tictactoe_motion.canvas_drawing import CanvasDrawing
    from tictactoe_motion.drawing_actions import DrawingActions
    from tictactoe_gui.game_coordinator import GameCoordinator, THREE_STONE_MODE
    from tictactoe_gui.perception_preview import StablePlayerMove
    from tictactoe_motion.simulated_board import SimulatedBoard
    from tictactoe_motion.simulation_driver import SimulationDriver
    from tictactoe_motion.simulation_scene import verify_scene

    profile = yaml.safe_load((Path(get_package_share_directory('tictactoe_motion'))/'config/board_sim.yaml').read_text())
    driver = SimulationDriver(session.output, install_signal_handlers=False)
    renderer = None
    stopped = {'handled': False}
    frame = {'message': None, 'sequence': 0, 'last_preview': 0.0}
    bridge = CvBridge()

    def receive_camera(message):
        frame['message'] = message
        frame['sequence'] += 1
        now = time.monotonic()
        if now - frame['last_preview'] < .45:
            return
        frame['last_preview'] = now
        try:
            image = bridge.imgmsg_to_cv2(message, 'bgr8')
            if image.shape[1] > 768:
                height = round(image.shape[0] * 768 / image.shape[1])
                image = cv2.resize(image, (768, height), interpolation=cv2.INTER_AREA)
            ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                session.publish_camera(encoded.tobytes())
        except (CvBridgeError, cv2.error) as error:
            print('CANVAS_CAMERA_FAILED', repr(error), flush=True)
    def check_stop():
        if session.stop.is_set() and not stopped['handled']:
            stopped['handled'] = True
            driver.execution.stop.request()
    timer = driver.client.create_timer(.04, check_stop)
    subscription = driver.client.create_subscription(
        Image, '/camera1/image_raw', receive_camera, qos_profile_sensor_data)
    driver.motion_guard = session.stop.is_set
    canvas = BoardCanvas(profile)
    try:
        driver.preflight();verify_scene(profile)
        renderer = SimulatedBoard(driver.client, profile, session.output/'ink', driver.result, grouped=True)
        driver.until(lambda: renderer.spawn.service_is_ready() and renderer.delete.service_is_ready())
        original_path = driver.path
        def painted_path(poses, *, speed=None):
            result = original_path(poses, excursion_limit=.75, speed=speed)
            renderer.paint(driver.results[-1]['samples'])
            return result
        driver.path = painted_path

        class GameMotion:
            """Use simulation-only speed limits for each phase of a mark."""

            def __init__(self, draw_speed):
                self.draw_speed = draw_speed

            def current_pose(self):
                return driver.current_pose()

            def pose(self, target):
                current = self.current_pose().position
                if abs(current.z - target.position.z) <= .0003:
                    return self.linear(target.position)
                return driver.pose(target)

            def linear(self, target):
                current = self.current_pose().position
                if abs(target.z - current.z) > .001:
                    return driver.linear(target, speed=.020)

                dx, dy = target.x - current.x, target.y - current.y
                if math.dist((current.x, current.y, current.z), (target.x, target.y, target.z)) <= .00001:
                    return {'passed': True, 'skipped': True}
                distance = math.hypot(dx, dy)
                started = time.monotonic()
                result = driver.linear(target, speed=.040, allow_excursion_retry=distance > .060)
                if result is not None:
                    return result

                print(f'GAME_HOVER_SPLIT distance_mm={distance*1000:.1f} '
                      f'rejected_plan_wall_s={time.monotonic()-started:.3f}', flush=True)
                # Only subdivide a rejected plan; it has already been invalidated.
                midpoint = copy.deepcopy(target)
                midpoint.x = current.x + dx / 2
                midpoint.y = current.y + dy / 2
                self.linear(midpoint)
                return self.linear(target)

            def path(self, poses):
                return painted_path(poses, speed=self.draw_speed)

        class GameActions(DrawingActions):
            def draw_x(self, center=(.5, .5), size=.012, **options):
                if not fast_game:
                    return super().draw_x(center, size, **options)
                return self.draw_fast(self.x_strokes(center, size), .032, **options)

            def draw_o(self, center=(.5, .5), radius=.005, samples=128, **options):
                if not fast_game:
                    return super().draw_o(center, radius, samples, **options)
                return self.draw_fast(self.o_strokes(center, radius, samples), .036, **options)

            def draw_fast(self, strokes, speed, **options):
                names = ('velocity_scaling', 'acceleration_scaling')
                previous = {name: driver.node.get_parameter(name).value for name in names}
                driver.parameters(velocity_scaling=.45, acceleration_scaling=.40)
                try:
                    stages = self._prepare(strokes).run(GameMotion(speed), **options)
                finally:
                    driver.parameters(**previous)
                return {'passed': True, 'stages': stages}

            def draw_grid(self, center, width, height, *, rows, columns, **options):
                lines = self.grid_strokes(center, width, height, rows, columns)
                renderer.set_grid([canvas.stroke(line, snap=False) for line in lines])
                return {'passed': True}

        actions = GameActions(canvas, driver)
        game = GameCoordinator(actions, session.update, session.stop.is_set)

        def read_player_mark(baseline):
            gate = StablePlayerMove(baseline, game.player_mark)
            accepted_frames = []
            for _ in range(12):
                if session.stop.is_set():
                    raise RuntimeError("任务已停止")
                # Sample the live camera only after the arm has returned to zero.
                ready_at = time.monotonic() + .20
                driver.until(lambda: time.monotonic() >= ready_at, 3)
                sequence = frame["sequence"]
                driver.until(lambda: frame["sequence"] > sequence, 3)
                raw = bridge.imgmsg_to_cv2(frame["message"], "bgr8")
                ok, encoded = cv2.imencode(".png", raw)
                if not ok:
                    raise RuntimeError("相机图像编码失败")
                cells = perception.detect_cells(encoded.tobytes())
                sequence = frame["sequence"]
                accepted_frames.append(dict(
                    sequence=sequence,
                    cells={f"{r+1},{c+1}": sorted(marks) for (r, c), marks in cells.items()},
                ))
                found = gate.observe(sequence, cells)
                if found is not None:
                    return found, accepted_frames
            raise RuntimeError("相机未确认唯一的新棋子，请检查板面后重新开局")

        session.update(state='ready', message='仿真已连接，可以绘制', busy=False)
        parked_over_board = False

        def fresh_pose_available():
            if not driver.node.feedback_is_fresh():
                return False
            try:
                driver.current_pose()
            except ValueError:
                return False
            return True

        while not session.shutdown.is_set():
            driver.executor.spin_once(timeout_sec=.02)
            try:
                job = session.jobs.get_nowait()
            except queue.Empty:
                continue
            started = time.monotonic()
            driver.results = []
            stopped['handled'] = False
            evidence = copy.deepcopy(job)
            try:
                if driver.execution.is_executing or driver.execution.stop.blocked:
                    raise RuntimeError('停稳尚未确认，拒绝新运动')
                driver.preflight();verify_scene(profile)
                if fast_game:
                    # Scene verification can block spinning long enough to age feedback.
                    driver.until(fresh_pose_available, 3)
                # Validate every segment before any movement, not just the first one.
                segments = [(part, CanvasDrawing(canvas, [part['points']],
                             upper_z=profile['hover_link6_z_m'],
                             depth=profile['hover_link6_z_m']-profile['drawing_link6_z_m'], snap=False))
                            for part in job['prepared']]
                session.update(state='running', message='前往悬空起点')
                kind = job['kind']
                if session.stop.is_set():
                    raise RuntimeError('任务已停止')
                request = job['game_request'] or {}
                opening_motion = (kind == 'game_start' and
                                  (request.get('first') == 'ai' or request.get('mode') == THREE_STONE_MODE)
                                  or kind == 'game_next' and game.human == 'X')
                game_job = kind.startswith('game_')
                needs_motion = kind not in ('game_start', 'game_next') or opening_motion
                reuse_hover = (fast_game and game_job and parked_over_board
                               and abs(driver.current_pose().position.z - canvas.profile['hover_link6_z_m'])
                               <= driver.node.settings['return_position_tolerance'])
                parked_over_board = False
                if needs_motion and not reuse_hover:
                    driver.named('clear')
                if kind == 'game_start':
                    request = job['game_request']
                    game.start(request['size'], job['job'], mode=request.get('mode', 'classic'),
                               first=request.get('first', 'player'), mark=request.get('mark', 'X'),
                               input_source=request.get('input_source', 'click'))
                elif kind == 'game_next':
                    game.next_round(job['job'])
                elif kind == 'game_move':
                    move = job['game_request']
                    game.move(move['row'], move['col'], job['job'])
                elif kind == 'game_vision_move':
                    baseline = session.status()['game']['board']
                    center = game.game.cell_center(request['row'], request['col'])
                    mark = game.player_mark
                    session.update(message=f'正在模拟玩家写 {mark}')
                    if mark == 'X':
                        actions.draw_x(center, game.game.cell_size*.55, cancelled=session.stop.is_set)
                    else:
                        actions.draw_o(center, game.game.cell_size*.25, cancelled=session.stop.is_set)
                    driver.named('zero')
                    session.update(message='等待相机确认新落子')
                    found, frames = read_player_mark(baseline)
                    evidence.update(observed_move=found, observations=frames)
                    if session.stop.is_set():
                        raise RuntimeError('任务已停止')
                    # The only player move submitted to the coordinator is the camera result.
                    driver.named('clear')
                    game.register_observed_move(*found, job['job'])
                    driver.named('zero')
                    needs_motion = reuse_hover = False
                elif kind == 'reset':
                    target = copy.deepcopy(driver.current_pose())
                    target.position.x, target.position.y = profile['reset_center'][:2]
                    target.position.z = profile['hover_link6_z_m']
                    driver.pose(target)
                    lower = copy.deepcopy(target.position);lower.z = profile['drawing_link6_z_m']
                    driver.linear(lower)
                    if not renderer.press_reset(driver.results[-1]['samples']):
                        raise RuntimeError('未确认仿真Reset动作')
                    driver.linear(target.position)
                    game.game = None
                    session.update(game=None, game_frame=None)
                else:
                    for index, (part, drawing) in enumerate(segments):
                        def stage(name):
                            event = dict(stroke=part['stroke'], part=part['part'], stage=name)
                            with session.lock:
                                session.state['events'].append(event)
                                session.state.update(stroke=part['stroke'], stage=name,
                                    message=f"第 {part['stroke']} / {session.state['total']} 笔 · 第 {part['part']} 段 · "+
                                    {'approach':'移动到起点','lower':'落笔','draw':'绘制','lift':'抬笔','transfer':'移笔'}.get(name.split('_')[-1],name))
                        drawing.run(driver, cancelled=session.stop.is_set, on_stage=stage)
                        if index+1 == len(segments) or segments[index+1][0]['stroke'] != part['stroke']:
                            session.update(completed=part['stroke'])
                if fast_game and game_job and (needs_motion or reuse_hover):
                    phase = session.status()['game']['phase']
                    if phase in ('player', 'between_rounds'):
                        parked_over_board = (
                            abs(driver.current_pose().position.z - canvas.profile['hover_link6_z_m'])
                            <= driver.node.settings['return_position_tolerance'])
                if (needs_motion or reuse_hover) and not parked_over_board:
                    session.update(message='已抬笔，正在回到 zero')
                    driver.named('zero')
                # Capture camera evidence after the final motion of the job.
                # Allow the sensor to render the just-spawned grid before saving evidence.
                ready_at = time.monotonic() + .5
                driver.until(lambda: time.monotonic() >= ready_at, 5)
                frame['message'] = None
                driver.until(lambda: frame['message'] is not None, 10)
                cv2.imwrite(str(session.output/f"job-{job['job']}.png"),
                            bridge.imgmsg_to_cv2(frame['message'], 'bgr8'))
                if kind.startswith('game_'):
                    session.update(game_frame=job['job'])
                    evidence['game'] = session.status()['game']
                evidence.update(passed=True, events=session.status()['events'])
                messages = {'draw': '绘制完成，已回到 zero', 'reset': '平板已清空，已回到 zero',
                            'game_start': '棋盘就绪，请落子', 'game_move': '本轮绘制完成',
                            'game_next': '第二局已开始，轮到你了',
                            'game_vision_move': '相机已确认玩家落子，本轮完成'}
                session.update(state='done', message=messages[kind])
            except BaseException as error:
                parked_over_board = False
                if job['kind'] in ('game_move', 'game_vision_move', 'game_next', 'reset') and game.game is not None:
                    game.block(job['job'])
                evidence.update(passed=False, error=repr(error))
                if driver.execution.is_executing:
                    driver.execution.stop.request()
                    try:
                        driver.until(lambda: not driver.execution.is_executing, 10)
                    except TimeoutError:
                        pass
                blocked = driver.execution.is_executing or driver.execution.stop.blocked
                state = 'blocked' if blocked else 'stopped' if session.stop.is_set() else 'failed'
                message='已停止，剩余笔画未执行' if state=='stopped' else '执行检查失败，任务已停止；请查看运行日志'
                print('CANVAS_JOB_FAILED',repr(error),flush=True)
                session.update(state=state, message=message)
            finally:
                session.update(busy=False)
                evidence.update(elapsed_s=time.monotonic()-started, executions=driver.results,
                                final_status=session.status())
                (session.output/f"job-{job['job']}.json").write_text(json.dumps(evidence, ensure_ascii=False))
                session.jobs.task_done()
    finally:
        if renderer:
            renderer.close()
        driver.client.destroy_timer(timer)
        driver.client.destroy_subscription(subscription)
        driver.close()
