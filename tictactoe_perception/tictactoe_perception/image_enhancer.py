import numpy as np

class ImageEnhancer:
    """!
    @brief Enhance the brightness of BGR Numpy images.
    """
    def enhance(self, raw_image, beta):
        working_image = raw_image.astype(np.int16)
        working_image = working_image + beta
        working_image = np.clip(working_image, 0, 255)
        enhanced_image = working_image.astype(np.uint8)
        return enhanced_image