from enum import Enum


class PromptSectionType(Enum):
    ROLE = "ROLE"
    HISTORY = "HISTORY"
    CHUNKS = "CHUNKS"
    SYSTEM_INPUT = "SYSTEM-INPUT"
    USER_INPUT = "USER-INPUT"
    OUTPUT_FORMAT = "OUTPUT-FORMAT"