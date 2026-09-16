"""Non-blocking error reporting for Pygame applications."""
import logging
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"


def system_uses_dark_mode():
    """Return the Windows app-theme preference; use light mode when unavailable."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except (ImportError, OSError, FileNotFoundError):
        return False


def app_logger(name):
    LOG_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(LOG_DIR / f"{name}.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)
    return logger


def report(logger, context, exc):
    """Persist a full traceback while returning a short UI-safe message."""
    logger.exception("%s failed", context, exc_info=(type(exc), exc, exc.__traceback__))
    return f"{context} failed: {type(exc).__name__}. See logs/{logger.name}.log"
