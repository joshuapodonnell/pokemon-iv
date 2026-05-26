# pause_controller.py
import threading
import logging
from pynput import keyboard

log = logging.getLogger(__name__)

class PauseController:
    def __init__(self, pause_key='f9', quit_key='f10'):
        self._paused    = threading.Event()
        self._stop      = threading.Event()
        self._pause_key = pause_key
        self._quit_key  = quit_key
        self._listener  = keyboard.Listener(on_press=self._on_press)

    def start(self):
        self._listener.start()
        log.info(f"PauseController ready — [{self._pause_key.upper()}] pause/resume  "
                 f"[{self._quit_key.upper()}] clean quit")

    def stop(self):
        self._listener.stop()

    def wait_if_paused(self):
        if self._paused.is_set():
            log.info("[PAUSED] Press F9 to resume...")
            while self._paused.is_set() and not self._stop.is_set():
                self._paused.wait(timeout=0.2)
            if not self._stop.is_set():
                log.info("[RESUMED]")

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def _on_press(self, key):
        try:
            key_name = key.name  # special keys like F9 have .name
        except AttributeError:
            key_name = key.char  # regular chars

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