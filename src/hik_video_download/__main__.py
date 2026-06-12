import sys
from pathlib import Path

# Support running as a standalone script (e.g. PyInstaller bundle)
if __name__ == "__main__" and __package__ is None:
    _dir = str(Path(__file__).resolve().parent)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
    __package__ = "hik_video_download"

from hik_video_download.app import main

if __name__ == "__main__":
    main()

