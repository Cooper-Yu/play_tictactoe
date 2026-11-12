import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

class ImageRaw(Node):
    def __init__(self):
        super().__init__('image_raw')
        self.image_subscription = self.create_subscription(Image, '/image_raw', self.image_callback, 10)
        self.bridge = CvBridge()

    def image_callback(self, msg):
        self.get_logger().info(f'Image width: {msg.width} Image height: {msg.height} Image encoding: {msg.encoding}')
        raw_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        self.get_logger().info(f'Image shape: {raw_image.shape} Image dtype: {raw_image.dtype}')

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
