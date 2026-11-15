"""Bounded installed-launch checks on an isolated ROS domain; never sends motion goals."""

import json
import os
from pathlib import Path
import signal
import subprocess
import time

import rclpy
from rcl_interfaces.srv import GetParameters
from rclpy.parameter import parameter_value_to_python
from sensor_msgs.msg import Image


def main():
    output = Path(os.environ.get('CONFIG_CHECK_OUTPUT', '/tmp/tictactoe-config-validation'))
    output.mkdir(parents=True, exist_ok=True)
    rclpy.init()
    inspector = rclpy.create_node('configuration_inspector')
    report = []
    cases = [
        ('motion-default', 'tictactoe_motion', 'motion_demo', [], '/motion_planner',
         {'environment': 'real', 'use_sim_time': False, 'distance': 0.0,
          'planning_time': 5.0, 'settle_samples': 3}),
        ('motion-sim', 'tictactoe_motion', 'motion_demo', ['environment:=sim', 'distance:=0.005'],
         '/motion_planner', {'environment': 'sim', 'use_sim_time': True, 'distance': 0.005}),
        ('camera-default', 'tictactoe_perception', 'enhancement_demo', ['log_images:=true'],
         '/image_raw', {'environment': 'real', 'use_sim_time': False,
                        'camera_topic': '/camera/D435/color/image_raw', 'initial_brightness_beta': 0}),
        ('camera-sim', 'tictactoe_perception', 'enhancement_demo',
         ['environment:=sim', 'log_images:=true'], '/image_raw',
         {'environment': 'sim', 'use_sim_time': True, 'camera_topic': '/camera1/image_raw'}),
        ('camera-override', 'tictactoe_perception', 'enhancement_demo',
         ['camera_topic:=/custom_rgb', 'initial_brightness_beta:=22', 'log_images:=true'],
         '/image_raw', {'environment': 'real', 'camera_topic': '/custom_rgb', 'initial_brightness_beta': 22}),
    ]
    try:
        for label, package, executable, args, node_name, expected in cases:
            log_path = output / f'{label}.log'
            client = None
            publisher = None
            command = ['ros2', 'launch', package, f'{executable}.launch.py', *args]
            with log_path.open('w') as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True,
                                           env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONNOUSERSITE': '1'})
                try:
                    client = inspector.create_client(GetParameters, f'{node_name}/get_parameters')
                    deadline = time.monotonic() + 12.0
                    while not client.wait_for_service(timeout_sec=0.2):
                        assert process.poll() is None, log_path.read_text()
                        assert time.monotonic() < deadline, f'{label}: parameter service unavailable'
                    request = GetParameters.Request(names=list(expected))
                    future = client.call_async(request)
                    rclpy.spin_until_future_complete(inspector, future, timeout_sec=5.0)
                    assert future.done(), label
                    actual = dict(zip(expected, [parameter_value_to_python(v)
                                                 for v in future.result().values]))
                    assert actual == expected, (label, actual, expected)
                    if package == 'tictactoe_perception':
                        publisher = inspector.create_publisher(Image, expected['camera_topic'], 10)
                        image = Image(height=2, width=4, encoding='rgb8', step=12,
                                      data=[250, 10, 0] * 8)
                        deadline = time.monotonic() + 8.0
                        while 'Image shape: (2, 4, 3)' not in log_path.read_text():
                            image.header.stamp = inspector.get_clock().now().to_msg()
                            publisher.publish(image)
                            rclpy.spin_once(inspector, timeout_sec=0.1)
                            assert process.poll() is None, log_path.read_text()
                            assert time.monotonic() < deadline, f'{label}: no converted image'
                    assert process.poll() is None, log_path.read_text()
                    report.append({'case': label, 'parameters': actual, 'passed': True})
                finally:
                    if process.poll() is None:
                        process.send_signal(signal.SIGINT)
                        try:
                            process.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGTERM)
                            process.wait(timeout=5)
                    assert 'process has died' not in log_path.read_text(), log_path.read_text()
                    if publisher:
                        inspector.destroy_publisher(publisher)
                    if client:
                        inspector.destroy_client(client)
                    # Allow DDS discovery to remove the previous same-name server.
                    until = time.monotonic() + 0.5
                    while time.monotonic() < until:
                        rclpy.spin_once(inspector, timeout_sec=0.05)
        print(json.dumps(report, indent=2))
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    finally:
        inspector.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()