import re

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}


BAD_FN_CHARACTERS = re.compile(r"[\[\]()^\s#%&!@:+={}'~]")


def sanitize_filename(fn: str):
    if fn in WINDOWS_RESERVED_NAMES:
        fn = "_" + fn
    fn = BAD_FN_CHARACTERS.sub("_", fn)
    return fn
