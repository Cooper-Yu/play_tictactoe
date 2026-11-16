"""Simulation-only localization operations over the existing motion/recording modules."""
import copy
import hashlib
import json
import math
import queue
import time
from collections import deque


def workbench_worker(session):
    """! @brief Own ROS callbacks, actual feedback, recording and serialized motion."""
    import cv2
    from cv_bridge import CvBridge
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    from tictactoe_motion.simulation_driver import SimulationDriver

    shot_index = session.output/'screenshots.json'
    shots = json.loads(shot_index.read_text()) if shot_index.exists() else {}
    if not isinstance(shots, dict):
        raise ValueError('Screenshot index must be an object')
    if session.environment == 'real':
        from tictactoe_motion.real_robot_driver import RealRobotDriver
        driver = RealRobotDriver(session.output, install_signal_handlers=False)
    else:
        driver = SimulationDriver(session.output, install_signal_handlers=False)
    bridge = CvBridge()
    camera = {'subscription': None, 'topic': '', 'received': None, 'sequence': 0,
              'error': None, 'width': 0, 'height': 0, 'period_s': None}
    history = deque(maxlen=40)
    matched_shot = {'frame': None}
    stopping = {'handled': False}
    last_publish = {'at': 0., 'topics': 0.}

    def image_received(msg):
        try:
            image = bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                raise ValueError('JPEG conversion failed')
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec*1e-9
            frame = encoded.tobytes()
            history.append((stamp, frame, camera['topic'], msg.header.frame_id))
            now = time.monotonic()
            if camera['received'] is not None:
                interval = now-camera['received']
                camera['period_s'] = interval if camera['period_s'] is None else .8*camera['period_s']+.2*interval
            camera.update(received=now, sequence=camera['sequence']+1,
                          width=msg.width, height=msg.height, encoding=msg.encoding,
                          frame_id=msg.header.frame_id, stamp=stamp, error=None)
            with session.lock:
                session.frames['live'] = frame
        except Exception as error:
            camera['error'] = str(error)

    def switch_camera(topic):
        topics = dict(driver.client.get_topic_names_and_types())
        if 'sensor_msgs/msg/Image' not in topics.get(topic, []):
            raise ValueError('所选 topic 尚未发布 sensor_msgs/msg/Image')
        if camera['subscription'] is not None:
            driver.client.destroy_subscription(camera['subscription'])
        history.clear()
        with session.lock:
            session.frames.pop('live', None)
        camera.update(topic=topic, received=None, sequence=0, width=0, height=0, error=None, period_s=None)
        camera['subscription'] = driver.client.create_subscription(
            Image, topic, image_received, qos_profile_sensor_data)

    def refresh_records():
        driver.recording._reload()
        records = copy.deepcopy(driver.recording.recorder.poses)
        for name, record in records.items():
            shot = shots.get(name)
            if shot and shot.get('record_stamp') == record['pose_stamped']['header']['stamp']:
                path = (session.output/'screenshots'/shot['file']).resolve()
                if path.is_file() and path.parent == session.output/'screenshots':
                    with session.lock:
                        session.frames['record:'+name] = path.read_bytes()
                    record['screenshot'] = shot
        session.update(records=records)

    def tick():
        now = time.monotonic()
        if session.environment == 'real' and driver.execution.is_executing and not driver.node.feedback_is_fresh():
            session.stop.set()
        if session.stop.is_set() and not stopping['handled']:
            stopping['handled'] = True
            driver.execution.stop.request()
        if now-last_publish['at'] < .15:
            return
        last_publish['at'] = now
        fresh = driver.node.feedback_is_fresh()
        transform = driver.node.get_current_pose() if fresh else None
        pose = None
        if transform is not None:
            p, q = transform.transform.translation, transform.transform.rotation
            pose = dict(x=p.x, y=p.y, z=p.z, quaternion=[q.x, q.y, q.z, q.w],
                        rpy=[math.atan2(2*(q.w*q.x+q.y*q.z), 1-2*(q.x*q.x+q.y*q.y)),
                             math.asin(max(-1, min(1, 2*(q.w*q.y-q.z*q.x)))),
                             math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))])
        state = driver.node.current_joint_state
        joints = dict(zip(state.name, state.position)) if state is not None else {}
        age = now-camera['received'] if camera['received'] is not None else None
        meta = {key: value for key, value in camera.items() if key not in ('subscription', 'received')}
        threshold = min(10., max(5., 3*(camera['period_s'] or 0.)))
        meta.update(age_s=age, fresh=age is not None and age < threshold,
                    stale_after_s=threshold, fps=1/camera['period_s'] if camera['period_s'] else None)
        values = dict(pose=pose, joints=joints, fresh=fresh and pose is not None, camera=meta)
        if now-last_publish['topics'] > 2:
            last_publish['topics'] = now
            values['topics'] = sorted(name for name, types in driver.client.get_topic_names_and_types()
                                      if 'sensor_msgs/msg/Image' in types)
            if camera['subscription'] is None:
                candidates = ('/camera/D435/color/image_raw',) if session.environment == 'real' else ('/camera1/image_raw', '/camera/D435/color/image_raw')
                for topic in candidates:
                    if topic in values['topics']:
                        switch_camera(topic)
                        break
        session.update(**values)

    timer = driver.client.create_timer(.04, tick)
    driver.motion_guard = session.stop.is_set

    def capture_ready(snapshot):
        value = snapshot.header.stamp.sec+snapshot.header.stamp.nanosec*1e-9
        match = min(history, key=lambda item: abs(item[0]-value)) if history else None
        ready = (match is not None and abs(match[0]-value) <= .5
                 and camera['received'] is not None and time.monotonic()-camera['received'] < 2.)
        matched_shot['frame'] = match if ready else None
        return ready

    driver.recording.capture_ready = capture_ready

    def wait_plan():
        driver.until(lambda: not driver.node.is_planning, 25)
        if session.stop.is_set():
            raise RuntimeError('操作已停止，规划已清除')
        return driver.guard(2.)

    def perform(command):
        kind = command['kind']
        if session.environment == 'real' and kind in ('jog', 'preset', 'return', 'execute'):
            driver.preflight()
        if not driver.node.feedback_is_fresh():
            raise RuntimeError('关节反馈已过期')
        if driver.execution.is_executing or driver.execution.stop.blocked:
            raise RuntimeError('运动尚未停稳')
        if kind in ('jog', 'preset', 'return'):
            driver.node.invalidate_plan()
            session.update(plan=None)
            driver.parameters(velocity_scaling=command['speed'], acceleration_scaling=command['speed'])
        if kind == 'jog':
            session.update(message='正在规划小步移动')
            target = copy.deepcopy(driver.current_pose())
            setattr(target.position, command['axis'], getattr(target.position, command['axis'])+command['distance'])
            if not driver.node.cartesian_planner.request_linear_position(target.position):
                raise RuntimeError('小步移动规划请求被拒绝')
            wait_plan()
            session.update(message='正在执行小步移动并等待停稳')
            comparison = driver.verified_pose_result(driver.execute())
            session.update(comparison=comparison, plan=None)
        elif kind == 'preset':
            joints, target = driver.named_target(command['name'])
            if not driver.node.request_joint_plan(joints, target, command['name']):
                raise RuntimeError('预设规划被拒绝')
            summary = wait_plan()
            session.update(plan=dict(label=command['name'], **summary))
        elif kind == 'return':
            driver.parameters(record_name=command['name'])
            driver.call('load_pose')
            driver.call('plan_return')
            summary = wait_plan()
            session.update(plan=dict(label='返回 '+command['name'], **summary))
        elif kind == 'execute':
            if driver.node.planned_trajectory is None:
                raise RuntimeError('规划已失效，请重新规划')
            session.update(plan=None, message='执行轨迹并核对停稳结果')
            result = driver.execute()
            session.update(comparison=result)
            if not result.get('passed', False):
                raise RuntimeError('实际位姿核对未通过：'+str(result))
        elif kind == 'record':
            driver.until(lambda: camera['received'] is not None and time.monotonic()-camera['received'] < 2., 8)
            driver.parameters(record_name=command['name'], overwrite=command['overwrite'])
            matched_shot['frame'] = None
            session.update(plan=None, message='等待停稳并同步记录关节、TF 与截图')
            driver.call('record_pose')
            driver.until(lambda: driver.recording.last_status.get('state') in ('saved', 'failed', 'canceled'), 10)
            if driver.recording.last_status['state'] != 'saved':
                raise RuntimeError(driver.recording.last_status['message'])
            record = driver.recording.recorder.get_pose(command['name'])
            stamp = record['pose_stamped']['header']['stamp']
            value = stamp['sec']+stamp['nanosec']*1e-9
            match = matched_shot['frame']
            if match is None or abs(match[0]-value) > .5:
                refresh_records()
                raise RuntimeError('位姿已保存，但没有时间差小于 0.5 秒的截图，请检查相机时间源')
            directory = session.output/'screenshots'
            directory.mkdir(exist_ok=True)
            name = hashlib.sha256((command['name']+json.dumps(stamp)).encode()).hexdigest()+'.jpg'
            (directory/name).write_bytes(match[1])
            shots[command['name']] = dict(file=name, record_stamp=stamp, camera_stamp=match[0],
                                          delta_s=match[0]-value, topic=match[2], frame_id=match[3])
            temporary = shot_index.with_suffix('.tmp')
            temporary.write_text(json.dumps(shots, ensure_ascii=False, indent=2))
            temporary.replace(shot_index)
            refresh_records()
        elif kind == 'delete':
            driver.parameters(record_name=command['name'])
            driver.call('delete_pose')
            session.update(plan=None)
            shots.pop(command['name'], None)
            temporary = shot_index.with_suffix('.tmp')
            temporary.write_text(json.dumps(shots, ensure_ascii=False, indent=2))
            temporary.replace(shot_index)
            with session.lock:
                session.frames.pop('record:'+command['name'], None)
            refresh_records()
        elif kind == 'camera':
            switch_camera(command['topic'])

    try:
        refresh_records()
        if session.environment == 'real':
            while not session.shutdown.is_set():
                try:
                    driver.preflight()
                    break
                except (ValueError, RuntimeError, TimeoutError) as error:
                    session.update(state='connecting', message='等待真机接口：'+str(error))
                    until = time.monotonic()+.5
                    driver.until(lambda: session.shutdown.is_set() or time.monotonic() >= until, 1.)
            if session.shutdown.is_set():
                return
        else:
            driver.preflight()
        topics = dict(driver.client.get_topic_names_and_types())
        candidates = ('/camera/D435/color/image_raw',) if session.environment == 'real' else ('/camera1/image_raw', '/camera/D435/color/image_raw')
        for topic in candidates:
            if 'sensor_msgs/msg/Image' in topics.get(topic, []):
                switch_camera(topic)
                break
        session.update(state='ready', message=('真机' if session.environment == 'real' else '仿真')+'已连接；启动不会移动机械臂')
        while not session.shutdown.is_set():
            driver.executor.spin_once(timeout_sec=.02)
            if session.stop.is_set() and stopping['handled']:
                try:
                    session.jobs.get_nowait()
                    session.jobs.task_done()
                except queue.Empty:
                    pass
                if not driver.execution.stop.blocked and not driver.execution.is_executing:
                    session.update(state='ready', busy=False, plan=None, message='已停止，待执行规划已清除')
                    session.stop.clear()
                    stopping['handled'] = False
                continue
            try:
                command = session.jobs.get_nowait()
            except queue.Empty:
                continue
            try:
                session.update(state='running', message='正在处理 '+command['kind'])
                if session.stop.is_set():
                    raise RuntimeError('操作已取消')
                perform(command)
                session.update(state='ready', busy=False, message='操作完成')
            except Exception as error:
                driver.node.invalidate_plan()
                if driver.execution.is_executing:
                    driver.execution.stop.request()
                blocked = driver.execution.is_executing or driver.execution.stop.blocked
                session.update(state='blocked' if blocked else 'ready', busy=False,
                               plan=None, message=str(error))
            session.jobs.task_done()
    finally:
        driver.client.destroy_timer(timer)
        driver.close()
