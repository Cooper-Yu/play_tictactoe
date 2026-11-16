import numpy as np

class ImageEnhancer:
    """!
    @brief Enhance the brightness of BGR Numpy images.
    """
    def enhance(self, raw_image, beta, roi=None):
        if roi is None:
            processing_image = raw_image
        else:
            x, y, width, height = roi
            processing_image = raw_image[y:y + height, x:x + width]

        working_image = processing_image.astype(np.int16)
        working_image = working_image + beta
        working_image = np.clip(working_image, 0, 255)
        enhanced_image = working_image.astype(np.uint8)
        return enhanced_image
    def enhance_ink(self, raw_image, strength=50, tolerance=20, roi=None):
        """! @brief Brighten existing cyan/blue line pixels inside a manual board ROI.

        The ROI must exclude the blue frame. Positive local contrast separates
        faint strokes from a uniformly blue-tinted board. No line dilation,
        filling or reconstruction is performed; the source array is unchanged.
        """
        import cv2
        if roi is None:
            raise ValueError('请先框选黑色书写面，避开蓝色边框')
        if (isinstance(strength, bool) or not isinstance(strength, (int, float))
                or not np.isfinite(strength) or not 0 <= strength <= 100):
            raise ValueError('笔迹增强强度应在 0–100')
        if (isinstance(tolerance, bool) or not isinstance(tolerance, (int, float))
                or not np.isfinite(tolerance) or not 5 <= tolerance <= 45):
            raise ValueError('颜色容差应在 5–45')
        x, y, width, height = roi
        image = raw_image[y:y+height, x:x+width]
        if not image.size or raw_image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError('Expected a non-empty uint8 BGR image region')
        if strength == 0:
            return image.copy()
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        h, saturation, value = cv2.split(hsv)
        v = value.astype(np.float32)
        local = cv2.GaussianBlur(v, (0, 0), 3.)
        contrast = v-local
        color = ((np.abs(h.astype(np.int16)-100) <= tolerance)
                 & (saturation >= 30) & (value >= 15) & (contrast >= 3.))
        adjusted = hsv.copy()
        amount = strength/100.
        adjusted[:, :, 1] = np.clip(saturation.astype(np.float32)+40*amount, 0, 255).astype(np.uint8)
        adjusted[:, :, 2] = np.clip(v+120*amount, 0, 255).astype(np.uint8)
        brighter = cv2.cvtColor(adjusted, cv2.COLOR_HSV2BGR)
        alpha = np.clip(contrast/12., 0, 1)*color
        output = image.copy()
        selected = alpha > 0
        blended = image.astype(np.float32)*(1-alpha[:, :, None])+brighter*alpha[:, :, None]
        output[selected] = np.rint(blended[selected]).clip(0, 255).astype(np.uint8)
        return output