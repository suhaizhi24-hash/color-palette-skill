class ColorPaletteError(Exception):
    """Base exception for user-facing local pipeline errors."""


class UnsupportedImageError(ColorPaletteError):
    pass


class ImageReadError(ColorPaletteError):
    pass


class AnalysisError(ColorPaletteError):
    pass


class RenderError(ColorPaletteError):
    pass
