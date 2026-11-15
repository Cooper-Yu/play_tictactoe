"""Connect the tablet's serialized jobs to the existing Gazebo motion driver."""
import copy
import json
import queue
import time
from pathlib import Path


def simulation_worker(session):
    """! @brief Run ROS on one worker; accept stop requests during every spin cycle.

    The first GUI deliberately requires the validated simulation profile.
    It cannot dispatch hardware commands. A stopped/failed path is never
    automatically resumed; every new drawing is a fresh explicit job.
    """
    import cv2
    from ament_index_python.packages import get_package_share_directory
    from cv_bridge import CvBridge
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    import yaml
    from tictactoe_motion.board_canvas import BoardCanvas
    from tictactoe_motion.canvas_drawing import CanvasDrawing
    from tictactoe_motion.simulated_board import SimulatedBoard
    from tictactoe_motion.simulation_driver import SimulationDriver
    from tictactoe_motion.simulation_scene import verify_scene

    profile = yaml.safe_load((Path(get_package_share_directory('tictactoe_motion'))/'config/board_sim.yaml').read_text())
    driver = SimulationDriver(session.output, install_signal_handlers=False)
    renderer = None
    stopped = {'handled': False}
    frame = {'message': None}
    def check_stop():
        if session.stop.is_set() and not stopped['handled']:
            stopped['handled'] = True
            driver.execution.stop.request()
    timer = driver.client.create_timer(.04, check_stop)
    subscription = driver.client.create_subscription(
        Image, '/camera1/image_raw', lambda msg: frame.update(message=msg), qos_profile_sensor_data)
    driver.motion_guard = session.stop.is_set
    canvas = BoardCanvas(profile)
    try:
        driver.preflight();verify_scene(profile)
        renderer = SimulatedBoard(driver.client, profile, session.output/'ink', driver.result, grouped=True)
        driver.until(lambda: renderer.spawn.service_is_ready() and renderer.delete.service_is_ready())
        original_path = driver.path
        def painted_path(poses):
            result = original_path(poses, excursion_limit=.75)
            renderer.paint(driver.results[-1]['samples'])
            return result
        driver.path = painted_path
        session.update(state='ready', message='仿真已连接，可以绘制', busy=False)
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
                # Validate every segment before any movement, not just the first one.
                segments = [(part, CanvasDrawing(canvas, [part['points']],
                             upper_z=profile['hover_link6_z_m'],
                             depth=profile['hover_link6_z_m']-profile['drawing_link6_z_m'], snap=False))
                            for part in job['prepared']]
                session.update(state='running', message='前往悬空起点')
                driver.named('clear')
                if job['kind'] == 'reset':
                    target = copy.deepcopy(driver.current_pose())
                    target.position.x, target.position.y = profile['reset_center'][:2]
                    target.position.z = profile['hover_link6_z_m']
                    driver.pose(target)
                    lower = copy.deepcopy(target.position);lower.z = profile['drawing_link6_z_m']
                    driver.linear(lower)
                    if not renderer.press_reset(driver.results[-1]['samples']):
                        raise RuntimeError('未确认仿真Reset动作')
                    driver.linear(target.position)
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
                session.update(message='已抬笔，正在回到 zero')
                driver.named('zero')
                # Camera evidence is captured after the arm has left the board.
                frame['message'] = None
                driver.until(lambda: frame['message'] is not None, 10)
                cv2.imwrite(str(session.output/f"job-{job['job']}.png"),
                            CvBridge().imgmsg_to_cv2(frame['message'], 'bgr8'))
                evidence.update(passed=True, events=session.status()['events'])
                session.update(state='done', message='绘制完成，已回到 zero' if job['kind']=='draw' else '平板已清空，已回到 zero')
            except BaseException as error:
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
