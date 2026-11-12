import cv2
from tictactoe_perception.image_enhancer import ImageEnhancer
from tictactoe_perception.comparison import show_comparison
import rclpy
from tictactoe_perception.image_raw import ImageRaw

class EnhancementDemo:
    def __init__(self):
        self.image_enhancer = ImageEnhancer()
        cv2.namedWindow("Raw | Enhanced")
        cv2.createTrackbar(
            "Brightness",
            "Raw | Enhanced",
            255,
            510,
            lambda value: None
        )
    def process_image(self, raw_image):
        slider_value = cv2.getTrackbarPos("Brightness", "Raw | Enhanced")
        beta = slider_value - 255
        enhanced_image = self.image_enhancer.enhance(raw_image, beta)
        show_comparison(raw_image, enhanced_image)

def main(args=None):
    rclpy.init(args=args)
    demo = EnhancementDemo()
    node = ImageRaw(demo.process_image)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()