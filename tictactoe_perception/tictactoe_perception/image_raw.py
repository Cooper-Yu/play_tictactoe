import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from tictactoe_perception.image_enhancer import ImageEnhancer
from tictactoe_perception.comparison import show_comparison

class ImageRaw(Node):
    """!
    @brief Subscribe to camera images and convert them into BGR Numpy arrays.
    """

    def __init__(self):
        super().__init__('image_raw')
        self.image_subscription = self.create_subscription(Image, '/image_raw', self.image_callback, 10)
        self.bridge = CvBridge()
        self.image_enhancer = ImageEnhancer()

    def image_callback(self, msg):
        self.get_logger().info(f'Image width: {msg.width} Image height: {msg.height} Image encoding: {msg.encoding}')
        raw_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        self.get_logger().info(f'Image shape: {raw_image.shape} Image dtype: {raw_image.dtype}')
        enhanced_image = self.image_enhancer.enhance(raw_image, 20)
        show_comparison(raw_image, enhanced_image)

def main(args=None):
    rclpy.init(args=args)
    node = ImageRaw()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
