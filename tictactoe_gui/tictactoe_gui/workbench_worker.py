"""Localization operations over the existing motion and recording modules."""
import copy
import hashlib
import json
import math
import queue
import time
from collections import deque

from tictactoe_gui.feedback_recovery import FeedbackRecovery, recovery_sample


def workbench_worker(session):
    """! @brief Own ROS callbacks, actual feedback, recording and serialized motion."""
    import cv2
    from cv_bridge import CvBridge
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    from tictactoe_driver.simulation_driver import SimulationDriver

    shot_index = session.output/'screenshots.json'
    shots = json.loads(shot_index.read_text()) if shot_index.exists() else {}
    if not isinstance(shots, dict):
        raise ValueError('Screenshot index must be an object')
    if session.environment == 'real':
        from tictactoe_driver.real_robot_driver import RealRobotDriver
        driver = RealRobotDriver(session.output, install_signal_handlers=False)
        driver.on_motion_progress = lambda progress: session.update(motion_progress=progress)
    else:
        driver = SimulationDriver(session.output, install_signal_handlers=False)
    real_canvas = None
    if session.environment == 'real':
        from pathlib import Path
        import yaml
        from ament_index_python.packages import get_package_share_directory
        from tictactoe_motion.canvas.board_canvas import BoardCanvas
        profile_path = Path(get_package_share_directory('tictactoe_motion'))/'config/board_real.yaml'
        real_canvas = BoardCanvas(yaml.safe_load(profile_path.read_text()))
        session.update(canvas=dict(width_mm=(real_canvas.x1-real_canvas.x0)*1000,
                                   height_mm=(real_canvas.y1-real_canvas.y0)*1000,
                                   margin_mm=1., max_strokes=32, max_points=8000))
    bridge = CvBridge()
    camera = {'subscription': None, 'topic': '', 'received': None, 'sequence': 0,
              'error': None, 'width': 0, 'height': 0, 'period_s': None}
    history = deque(maxlen=40)
    matched_shot = {'frame': None}
    stopping = {'handled': False}
    last_publish = {'at': 0., 'topics': 0.}
    tick_timing = {'previous_at_s': None, 'last_gap_s': None, 'max_gap_s': 0.}

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
            raise ValueError('Selected topic Not published sensor_msgs/msg/Image')
        if camera['subscription'] is not None:
            driver.client.destroy_subscription(camera['subscription'])
        history.clear()
        with session.lock:
            session.frames.pop('live', None)
        camera.update(topic=topic, received=None, sequence=0, width=0, height=0, error=None, period_s=None)
        camera['subscription'] = driver.client.create_subscription(
            Image, topic, image_received, qos_profile_sensor_data)

    from tictactoe_motion.pose_recording.record_names import canonical_record_name

    def refresh_records():
        driver.recording._reload()
        records = copy.deepcopy(driver.recording.recorder.poses)
        for name, record in records.items():
            shot = shots.get(name)
            if shot and shot.get('record_stamp') == record['pose_stamped']['header']['stamp']:
                path = (session.output/'screenshots'/shot['file']).resolve()
                if path.is_file() and path.parent == session.output/'screenshots':
                    with session.lock:
                        session.frames['record:'+canonical_record_name(name)] = path.read_bytes()
                    record['screenshot'] = shot
        displayed = {}
        for name, record in records.items():
            display_name = canonical_record_name(name)
            record["name"] = display_name
            if display_name not in displayed or name == display_name:
                displayed[display_name] = record
        session.update(records=displayed)

    def tick():
        now = time.monotonic()
        previous = tick_timing['previous_at_s']
        if previous is not None:
            gap = now-previous
            tick_timing.update(last_gap_s=gap, max_gap_s=max(gap, tick_timing['max_gap_s']))
        tick_timing['previous_at_s'] = now
        timing = dict(joints=driver.node.feedback_snapshot(now), executor_tick=dict(tick_timing))
        if (session.environment == 'real' and driver.execution.is_executing
                and not driver.node.feedback_is_fresh() and not session.stop.is_set()):
            print('WORKBENCH_FEEDBACK_STALE '+json.dumps(timing), flush=True)
            received = driver.node.last_joint_state_received
            age = now-received if received is not None else None
            session.request_stop('Joint feedback became stale during execution: age='+str(age)
                                 +'s, limit='+str(driver.node.settings['feedback_max_age'])+'s',
                                 source='feedback_guard')
        if session.stop.is_set() and not stopping['handled']:
            stopping['handled'] = True
            if session.recovery is None:
                driver.execution.stop.request()
            else:
                driver.execution.stop.request(confirmation_timeout=FeedbackRecovery.timeout)
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
        if pose is not None:
            session.last_known_pose = pose
        if session.recovery is not None:
            sample = recovery_sample(
                now, driver.node.get_clock().now().nanoseconds*1e-9, state, transform,
                driver.node.last_joint_state_received, driver.node.settings['feedback_max_age'],
            )
            stopped = not driver.execution.is_executing and not driver.execution.stop.blocked
            session.observe_recovery(now, stopped, sample, driver.node.settings['settle_joint_tolerance'])
        age = now-camera['received'] if camera['received'] is not None else None
        meta = {key: value for key, value in camera.items() if key not in ('subscription', 'received')}
        threshold = min(10., max(5., 3*(camera['period_s'] or 0.)))
        meta.update(age_s=age, fresh=age is not None and age < threshold,
                    stale_after_s=threshold, fps=1/camera['period_s'] if camera['period_s'] else None)
        values = dict(pose=pose, joints=joints, fresh=fresh and pose is not None, camera=meta,
                      feedback_diagnostics=timing)
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
            raise RuntimeError('Operation stopped, Plan cleared')
        return driver.guard(2.)

    def perform(command):
        kind = command['kind']
        if session.environment == 'real' and kind in ('jog', 'preset', 'return', 'execute', 'reset', 'draw', 'canvas'):
            driver.preflight()
        if not driver.node.feedback_is_fresh():
            raise RuntimeError('Joint feedback is stale')
        if driver.execution.is_executing or driver.execution.stop.blocked:
            raise RuntimeError('Motion has not settled')
        if kind in ('jog', 'preset', 'return'):
            driver.node.invalidate_plan()
            session.update(plan=None)
            driver.parameters(velocity_scaling=command['speed'], acceleration_scaling=command['speed'])
        if kind == 'jog':
            session.update(message='Planning jog')
            target = copy.deepcopy(driver.current_pose())
            setattr(target.position, command['axis'], getattr(target.position, command['axis'])+command['distance'])
            if not driver.node.cartesian_planner.request_linear_position(target.position):
                raise RuntimeError('Jog planning request rejected')
            wait_plan()
            session.update(message='Executing jog and waiting for settling')
            comparison = driver.verified_pose_result(driver.execute())
            session.update(comparison=comparison, plan=None)
        elif kind == 'preset':
            joints, target = driver.named_target(command['name'])
            if not driver.node.request_joint_plan(joints, target, command['name']):
                raise RuntimeError('Preset planning rejected')
            summary = wait_plan()
            session.update(plan=dict(label=command['name'], **summary))
        elif kind == 'return':
            driver.parameters(record_name=command['name'])
            driver.call('load_pose')
            driver.call('plan_return')
            summary = wait_plan()
            session.update(plan=dict(label='Return '+command['name'], **summary))
        elif kind == 'execute':
            if driver.node.planned_trajectory is None:
                raise RuntimeError('Plan is no longer valid, Replan')
            session.update(plan=None, message='Execute trajectory and verify settling')
            result = driver.execute()
            session.update(comparison=result)
            if not result.get('passed', False):
                raise RuntimeError('Actual pose verification failed: '+str(result))
        elif kind == 'reset':
            from tictactoe_motion.actions.reset_action import ResetAction
            driver.node.invalidate_plan()
            session.update(plan=None, reset_result=None)
            result = ResetAction(driver, lambda stage: session.update(message=stage)).run(command['speed'], direct_native=session.environment == 'real')
            session.update(reset_result=result)
        elif kind == 'draw':
            from pathlib import Path
            import yaml
            from ament_index_python.packages import get_package_share_directory
            from tictactoe_motion.actions.drawing_actions import DrawingActions
            if session.environment != 'real':
                raise ValueError('Real drawing profile required')
            profile_path = Path(get_package_share_directory('tictactoe_motion'))/'config/board_real.yaml'
            profile = yaml.safe_load(profile_path.read_text())
            canvas = BoardCanvas(profile)
            if canvas.environment != session.environment:
                raise ValueError('Drawing environment mismatch')
            if command['speed'] > profile['max_velocity_scaling']:
                raise ValueError('Drawing speed exceeds the calibrated profile limit')
            actions = DrawingActions(canvas, driver)
            center, size = command['center'], command['size']
            if command['shape'] in ('smile', 'docker', 'chair'):
                from tictactoe_motion.canvas.illustration_drawing import IllustrationDrawing
                illustration = IllustrationDrawing(actions)
                strokes = illustration.strokes(command['shape'], center=center, width=size)
                skip = command['skip_strokes']
                if skip >= len(strokes):
                    raise ValueError('Resume stroke index is outside the illustration')
                drawings = illustration._batches(strokes[skip:])
            else:
                if command['shape'] == 'x':
                    strokes = actions.x_strokes(center, size)
                elif command['shape'] == 'o':
                    strokes = actions.o_strokes(center, size/2)
                else:
                    strokes = actions.grid_strokes(center, size, size)
                drawings = [actions._prepare(strokes)]
            # Validate every batch against real heights/bounds before any movement.
            driver.node.invalidate_plan()
            session.update(plan=None, drawing_result=None, drawing_progress=None)
            driver.parameters(velocity_scaling=command['speed'], acceleration_scaling=command['speed'])
            stages = []
            for index, drawing in enumerate(drawings, 1):
                def on_stage(stage):
                    session.update(message='Drawing: '+stage,
                                   drawing_progress=dict(shape=command['shape'], batch=index,
                                                         batches=len(drawings), stage=stage,
                                                         completed_batches=index-1,
                                                         completed_stages=len(stages)+len(drawing.results),
                                                         skipped_strokes=command['skip_strokes']))
                stages.extend(drawing.run(driver, cancelled=session.stop.is_set, on_stage=on_stage))
            session.update(drawing_result=dict(motion_completed=True, ink_confirmed=None,
                                               shape=command['shape'], strokes=len(strokes),
                                               skipped_strokes=command['skip_strokes'], stages=stages))
        elif kind == 'canvas':
            from tictactoe_gui.canvas_action import CanvasAction
            if real_canvas is None or command['speed'] > real_canvas.profile['max_velocity_scaling']:
                raise ValueError('Real canvas calibration or speed does not match the profile')
            canvas = real_canvas
            if command.get('direct_from_zero'):
                canvas = BoardCanvas(dict(real_canvas.profile, allow_direct_zero_approach=True))
            action = CanvasAction(canvas, command['strokes'])
            driver.node.invalidate_plan()
            session.update(plan=None, drawing_result=None, drawing_progress=None)
            driver.parameters(velocity_scaling=command['speed'], acceleration_scaling=command['speed'])
            report = dict(submitted_strokes=command['strokes'], prepared=action.prepared,
                          speed=command['speed'], environment='real', motion_completed=False)
            directory = session.output/'canvas'
            directory.mkdir(exist_ok=True)
            destination = directory/(str(time.time_ns())+'-job-'+str(session.status()['job'])+'.json')
            def progress(value):
                session.update(message=f'Canvas: Stroke {value["source_stroke"]}/{action.input_count} · '+value['stage'],
                               drawing_progress=value)
            try:
                result = action.run(driver, cancelled=session.stop.is_set, on_stage=progress)
                session.update(message='Canvas: returning to clear',
                               drawing_progress=dict(stage='return_clear',
                                                     source_stroke=action.input_count,
                                                     total_input_strokes=action.input_count))
                action.return_to_clear(driver, cancelled=session.stop.is_set)
                result.update(returned_to_clear=True, stages=copy.deepcopy(action.stages))
                report.update(result)
                session.update(drawing_result=dict(result, report=str(destination)))
            except BaseException as error:
                report.update(error=str(error), stages=action.stages)
                raise
            finally:
                destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        elif kind == 'record':
            driver.until(lambda: camera['received'] is not None and time.monotonic()-camera['received'] < 2., 8)
            driver.parameters(record_name=command['name'], overwrite=command['overwrite'])
            matched_shot['frame'] = None
            session.update(plan=None, message='Wait for settling and record joints, TF and screenshot')
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
                raise RuntimeError('Pose saved, but no screenshot was found within 0.5 seconds of the pose timestamp, Check the camera time source')
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
                    session.update(state='connecting', message='Waiting for robot interfaces: '+str(error))
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
        session.update(state='ready', message=('Robot' if session.environment == 'real' else 'Simulation')+'connected; Startup does not move the arm')
        while not session.shutdown.is_set():
            driver.executor.spin_once(timeout_sec=.02)
            if session.stop.is_set() and stopping['handled']:
                try:
                    session.jobs.get_nowait()
                    session.jobs.task_done()
                except queue.Empty:
                    pass
                if not driver.execution.stop.blocked and not driver.execution.is_executing:
                    session.finish_stop()
                    stopping['handled'] = False
                continue
            try:
                command = session.jobs.get_nowait()
                driver.reset_motion_progress()
            except queue.Empty:
                continue
            try:
                session.active_operation = command['kind']
                if command['kind'] in ('draw', 'canvas', 'reset'):
                    session.update(drawing_progress=None)
                session.update(state='running', message='Processing '+command['kind'])
                if session.stop.is_set():
                    raise RuntimeError('Operation cancelled')
                perform(command)
                session.update(state='ready', busy=False, message=('Reset completed; returned to clearance pose. Confirm that the board is clear.' if command['kind'] == 'reset' else 'Drawing completed; returned to clear. Check the actual ink.' if command['kind'] == 'canvas' else 'Drawing motion completed; pen raised. Check the actual ink.' if command['kind'] == 'draw' else 'Operation completed'))
            except Exception as error:
                driver.node.invalidate_plan()
                if driver.execution.is_executing and not session.stop.is_set():
                    driver.execution.stop.request()
                blocked = driver.execution.is_executing or driver.execution.stop.blocked
                if not session.stop.is_set() or session.recovery is None:
                    session.update(state='blocked' if blocked else 'ready', busy=False,
                                   plan=None, message=str(error))
            finally:
                session.active_operation = None
                session.jobs.task_done()
    finally:
        driver.client.destroy_timer(timer)
        driver.close()
