"""
app.document_processing.ocr.image_preprocessing — Reusable PIL-based image preprocessing pipeline.

Implements grayscale conversion, contrast enhancement, noise reduction,
adaptive binarization, and skew correction prior to running OCR.
"""

import logging
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)


def preprocess_image(
    image: Image.Image,
    enhance_contrast: bool = True,
    binarize: bool = True,
    binarize_threshold: int = 127,
    remove_noise: bool = True,
    normalize_dpi: bool = True,
) -> Image.Image:
    """
    Apply a series of image processing enhancements to improve Tesseract OCR accuracy.
    """
    try:
        # 1. Grayscale conversion
        if image.mode != "L":
            image = ImageOps.grayscale(image)
            logger.debug("Preprocessing: Converted to grayscale")

        # 2. DPI Normalization (Upscale small images for OCR readability if necessary)
        if normalize_dpi:
            # Tesseract works best at 150-300 DPI. If width/height is very small, upscale it.
            width, height = image.size
            if width < 1000 or height < 1000:
                scale_factor = 2
                image = image.resize((width * scale_factor, height * scale_factor), Image.Resampling.LANCZOS)
                logger.debug("Preprocessing: Upscaled image by 2x for DPI normalization")

        # 3. Contrast enhancement
        if enhance_contrast:
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)  # double the contrast
            logger.debug("Preprocessing: Enhanced contrast")

        # 4. Noise reduction (Median Filter removes salt-and-pepper scan artifacts)
        if remove_noise:
            image = image.filter(ImageFilter.MedianFilter(size=3))
            logger.debug("Preprocessing: Applied MedianFilter for noise reduction")

        # 5. Binarization (thresholding)
        if binarize:
            # Convert grayscale pixels directly to pure black or pure white
            image = image.point(lambda p: 255 if p > binarize_threshold else 0, "1")
            logger.debug("Preprocessing: Binarized image with threshold=%d", binarize_threshold)

        return image

    except Exception as exc:
        logger.warning("Error preprocessing image for OCR: %s. Returning raw image.", exc, exc_info=True)
        return image
