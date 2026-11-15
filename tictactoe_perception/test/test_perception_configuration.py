"""Camera configuration and brightness behavior without a desktop display."""

from unittest.mock import Mock
import numpy as np
import pytest
import rclpy
from sensor_msgs.msg import Image
from rclpy.qos import ReliabilityPolicy
from tictactoe_perception.image_raw import ImageRaw
from tictactoe_perception.enhancement_demo import EnhancementDemo
import tictactoe_perception.enhancement_demo as module


def test_camera_qos_bgr_conversion_and_configured_brightness(monkeypatch):
    rclpy.init(args=['--ros-args', '-p', 'camera_topic:=/test/rgb', '-p',
                     'initial_brightness_beta:=22', '-p', 'window_name:=Test Preview'])
    node = ImageRaw(None)
    try:
        for name in ('namedWindow', 'createTrackbar', 'setMouseCallback', 'rectangle'):
            monkeypatch.setattr(module.cv2, name, Mock())
        monkeypatch.setattr(module.cv2, 'getTrackbarPos', Mock(return_value=277))
        show = Mock()
        monkeypatch.setattr(module, 'show_comparison', show)
        demo = EnhancementDemo(node)
        node.on_image = demo.process_image
        assert node.image_subscription.topic_name == '/test/rgb'
        assert node.image_subscription.qos_profile.reliability == ReliabilityPolicy.BEST_EFFORT
        module.cv2.createTrackbar.assert_called_once()
        assert module.cv2.createTrackbar.call_args.args[:4] == ('Brightness', 'Test Preview', 277, 510)
        msg = Image(height=1, width=2, encoding='rgb8', step=6,
                    data=[250, 10, 0, 0, 10, 250])
        node.image_callback(msg)
        raw, enhanced, name = show.call_args.args
        assert name == 'Test Preview'
        np.testing.assert_array_equal(raw, [[[0, 10, 250], [250, 10, 0]]])
        np.testing.assert_array_equal(enhanced, [[[22, 32, 255], [255, 32, 22]]])
        demo.roi = (1, 0, 1, 1)
        demo.process_image(raw)
        assert show.call_args.args[1].shape == (1, 1, 3)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


@pytest.mark.parametrize('parameter', ['initial_brightness_beta:=256', 'camera_queue_depth:=0',
                                      'camera_reliability:=invalid', 'environment:=invalid'])
def test_invalid_camera_config_rejected(parameter):
    rclpy.init(args=['--ros-args', '-p', parameter])
    try:
        with pytest.raises(ValueError):
            ImageRaw(Mock())
    finally:
        rclpy.try_shutdown()