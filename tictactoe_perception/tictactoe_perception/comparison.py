import numpy as np
import cv2

def show_comparison(raw_image, enhanced_image, window_name="Raw | Enhanced"):
    target_height, target_width = raw_image.shape[:2]
    source_height, source_width = enhanced_image.shape[:2]
    scale = min(target_width / source_width, target_height / source_height
    )
    resized_width = max(1, int(source_width * scale))
    resized_height = max(1, int(source_height * scale))
    resize_image = cv2.resize(
        enhanced_image,
        (resized_width, resized_height),
        interpolation=cv2.INTER_LINEAR
    )
    display_image = np.zeros_like(raw_image)
    offset_x = (target_width - resized_width) // 2
    offset_y = (target_height - resized_height) // 2
    display_image[
    offset_y:offset_y + resized_height,
    offset_x:offset_x + resized_width] = resize_image
    comparison_image = np.hstack((raw_image, display_image))
    cv2.imshow(window_name, comparison_image)
    cv2.waitKey(1)