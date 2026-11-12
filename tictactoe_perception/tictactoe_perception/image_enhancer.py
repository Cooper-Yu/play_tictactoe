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