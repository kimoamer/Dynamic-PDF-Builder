from enum import Enum

class Alignment(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"

class PageSize(str, Enum):
    A4 = "A4"
    LETTER = "LETTER"
    LEGAL = "LEGAL"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            upper = value.upper()
            for member in cls:
                if member.value == upper:
                    return member
        return None

class Orientation(str, Enum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"

class CalloutVariant(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    TIP = "tip"
