from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.qos import QoSProfile, ReliabilityPolicy


def declare_settings(node):
    """! @brief Validate camera and display startup settings before creating a subscriber."""
    defaults = {
        'environment': 'real',
        'camera_topic': '/camera/D435/color/image_raw',
        'camera_reliability': 'best_effort',
        'camera_queue_depth': 10,
        'initial_brightness_beta': 0,
        'window_name': 'Raw | Enhanced',
        'log_images': False,
    }
    values = {
        name: node.declare_parameter(name, default, ParameterDescriptor(read_only=True)).value
        for name, default in defaults.items()
    }
    if values['environment'] not in ('sim', 'real'):
        raise ValueError('environment must be sim or real')
    if values['camera_reliability'] not in ('best_effort', 'reliable'):
        raise ValueError('camera_reliability must be best_effort or reliable')
    if values['camera_queue_depth'] <= 0:
        raise ValueError('camera_queue_depth must be positive')
    if not -255 <= values['initial_brightness_beta'] <= 255:
        raise ValueError('initial_brightness_beta must be in [-255, 255]')
    for name in ('camera_topic', 'window_name'):
        if not values[name].strip():
            raise ValueError(f'{name} must be non-empty')
    return values


class ImageRaw(Node):
    """!
    @brief Subscribe to camera images and convert them into BGR Numpy arrays.
    """

    def __init__(self, on_image):
        super().__init__('image_raw')
        self.settings = declare_settings(self)
        self.on_image = on_image
        reliability = (
            ReliabilityPolicy.BEST_EFFORT if self.settings['camera_reliability'] == 'best_effort'
            else ReliabilityPolicy.RELIABLE
        )
        self.image_subscription = self.create_subscription(
            Image, self.settings['camera_topic'], self.image_callback,
            QoSProfile(depth=self.settings['camera_queue_depth'], reliability=reliability),
        )
        self.bridge = CvBridge()


    def image_callback(self, msg):
        if self.settings['log_images']:
            self.get_logger().info(f'Image width: {msg.width} Image height: {msg.height} Image encoding: {msg.encoding}')
        raw_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        if self.settings['log_images']:
            self.get_logger().info(f'Image shape: {raw_image.shape} Image dtype: {raw_image.dtype}')
        self.on_image(raw_image)
