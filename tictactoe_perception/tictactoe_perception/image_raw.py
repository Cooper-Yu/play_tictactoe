import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

class ImageRaw(Node):
    def __init__(self):
        super().__init__('image_raw')
        self.image_subscription = self.create_subscription(Image, '/image_raw', self.image_callback, 10)

    def image_callback(self, msg):
        self.get_logger().info(f'Image width: {msg.width} Image height: {msg.height} Image encoding: {msg.encoding}')

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
