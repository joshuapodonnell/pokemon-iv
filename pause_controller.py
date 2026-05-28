# pause_controller.py
import threading
import logging
from pynput import keyboard

log = logging.getLogger(__name__)

class PauseController:
    def __init__(self, pause_key='f9', quit_key='f10', reprocess_key='f8'):
        self._paused         = threading.Event()
        self._stop           = threading.Event()
        self._reprocess      = threading.Event()   # ← new
        self._pause_key      = pause_key
        self._quit_key       = quit_key
        self._reprocess_key  = reprocess_key       # ← new
        self._listener       = keyboard.Listener(on_press=self._on_press)

    def start(self):
        self._listener.start()
        log.info(
            f"PauseController ready — "
            f"[{self._pause_key.upper()}] pause/resume  "
            f"[{self._quit_key.upper()}] clean quit  "
            f"[{self._reprocess_key.upper()}] reprocess current"  # ← new
        )

    def stop(self):
        self._listener.stop()

    def wait_if_paused(self) -> bool:
        if not self._paused.is_set():
            return False
        log.info(f"[PAUSED] Press {self._pause_key.upper()} to resume, "
                 f"{self._reprocess_key.upper()} to reprocess current Pokémon...")
        while self._paused.is_set() and not self._stop.is_set():
            self._paused.wait(timeout=0.2)
        if not self._stop.is_set():
            log.info("[RESUMED]")
        return True

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def should_reprocess(self) -> bool:
        """Returns True once and resets the flag — call after wait_if_paused."""
        return self._reprocess.is_set() and not self._reprocess.clear()

    def _on_press(self, key):
        try:
            key_name = key.name
        except AttributeError:
            key_name = key.char

        if key_name == self._pause_key:
            if self._paused.is_set():
                self._paused.clear()
            else:
                self._paused.set()
                log.info("[PAUSING] Will pause after current Pokémon...")

        elif key_name == self._quit_key:
            log.info("[QUIT] Stopping after current Pokémon...")
            self._stop.set()
            self._paused.clear()  # unblock wait_if_paused so loop can exit

        elif key_name == self._reprocess_key:
            if self._paused.is_set():
                log.info("[REPROCESS] Reprocess requested for current Pokémon.")
                self._reprocess.set()
            else:
                log.info(f"[REPROCESS] Ignored — only works while paused.")