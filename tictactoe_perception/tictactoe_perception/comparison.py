import numpy as np
import cv2

def show_comparison(raw_image, enhanced_image):
    comparison_image = np.hstack((raw_image, enhanced_image))
    cv2.imshow("Raw | Enhanced", comparison_image)
    cv2.waitKey(1)