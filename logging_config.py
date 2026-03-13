"""
logging_config.py
-----------------
Merkezi logging konfigürasyonu.
Uygulama başlangıcında (app.py veya engine.py içinden) bir kez çağrılır.

Kullanım:
    from logging_config import setup_logging
    setup_logging()
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "selvese.log"
LOG_LEVEL_ENV = os.getenv("SELVESE_LOG_LEVEL", "WARNING").upper()


def setup_logging(level=None):
    """
    Logging sistemini başlat.

    - Console: WARNING ve üzeri (UI'da gürültü olmasın)
    - Dosya:   DEBUG ve üzeri, 7 günlük rotasyon (sorun ayıklamak için)

    Parameters
    ----------
    level : str | None
        Override log seviyesi. None ise SELVESE_LOG_LEVEL env değişkeni
        veya varsayılan WARNING kullanılır.
    """
    LOG_DIR.mkdir(exist_ok=True)

    root_level = getattr(logging, level or LOG_LEVEL_ENV, logging.WARNING)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Console handler ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)

    # --- Dosya handler (TimedRotating: her gece, 7 dosya sakla) ---
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=LOG_FILE,
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(root_level)

    # Daha önce eklenmiş handler varsa temizle (Streamlit hot-reload koruması)
    if root_logger.handlers:
        root_logger.handlers.clear()

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("streamlit").setLevel(logging.WARNING)

    logging.getLogger(__name__).debug("Logging sistemi başlatıldı (level=%s)", root_level)
