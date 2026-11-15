import cv2
from tictactoe_perception.image_enhancer import ImageEnhancer
from tictactoe_perception.comparison import show_comparison
import rclpy
from tictactoe_perception.image_raw import ImageRaw


class EnhancementDemo:
    """!
    @brief Manage brightness controls, image enhancement, and comparison display.
    """

    def __init__(self, node):
        self.window_name = node.settings['window_name']
        self.image_enhancer = ImageEnhancer()
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.createTrackbar(
            "Brightness", self.window_name, node.settings['initial_brightness_beta'] + 255,
            510, lambda value: None,
        )
        self.roi = None

        self.is_selecting = False
        self.selection_start = None
        self.selection_end = None

        self.image_width = 0
        self.image_height = 0

        cv2.setMouseCallback(self.window_name, self.on_mouse)

    def process_image(self, raw_image):
        self.image_height, self.image_width = raw_image.shape[:2]
        slider_value = cv2.getTrackbarPos("Brightness", self.window_name)
        beta = slider_value - 255
        enhanced_image = self.image_enhancer.enhance(raw_image, beta, self.roi)
        preview_image = raw_image.copy()
        if self.is_selecting:
            cv2.rectangle(
                preview_image, self.selection_start, self.selection_end, (0, 255, 0), 1
            )
        show_comparison(preview_image, enhanced_image, self.window_name)

    def on_mouse(self, event, x, y, flags, param):
        if (
            event == cv2.EVENT_LBUTTONDOWN
            and 0 <= x < self.image_width
            and 0 <= y < self.image_height
        ):
            self.is_selecting = True
            self.selection_start = (x, y)
            self.selection_end = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self.is_selecting:
            end_x = max(0, min(x, self.image_width - 1))
            end_y = max(0, min(y, self.image_height - 1))
            self.selection_end = (end_x, end_y)
        elif event == cv2.EVENT_LBUTTONUP and self.is_selecting:
            end_x = max(0, min(x, self.image_width - 1))
            end_y = max(0, min(y, self.image_height - 1))
            self.selection_end = (end_x, end_y)
            self.is_selecting = False
            start_x, start_y = self.selection_start
            end_x, end_y = self.selection_end
            roi_x = min(start_x, end_x)
            roi_y = min(start_y, end_y)
            roi_width = abs(end_x - start_x)
            roi_height = abs(end_y - start_y)
            if roi_width > 0 and roi_height > 0:
                self.roi = (roi_x, roi_y, roi_width, roi_height)


def main(args=None):
    rclpy.init(args=args)
    node = ImageRaw(None)
    try:
        demo = EnhancementDemo(node)
        node.on_image = demo.process_image
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
