# pause_controller.py
import threading
import sys
import termios
import tty
import logging

log = logging.getLogger(__name__)

class PauseController:
    def __init__(self):
        self._paused = threading.Event()
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True)

    def start(self):
        self._thread.start()
        log.info("PauseController: press 'p' to pause/resume, 'q' to quit cleanly.")

    def wait_if_paused(self):
        """Call this at the top of each scan loop iteration."""
        if self._paused.is_set():
            log.info("[PAUSED] Press 'p' to resume...")
            while self._paused.is_set() and not self._stop.is_set():
                self._paused.wait(timeout=0.2)
            if not self._stop.is_set():
                log.info("[RESUMED]")

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def _listen(self):
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while not self._stop.is_set():
                ch = sys.stdin.read(1)
                if ch == 'p':
                    if self._paused.is_set():
                        self._paused.clear()   # resume
                    else:
                        self._paused.set()     # pause
                        log.info("[PAUSING] Will pause after current Pokémon...")
                elif ch == 'q':
                    log.info("[QUIT] Stopping after current Pokémon...")
                    self._stop.set()
                    self._paused.clear()       # unblock wait_if_paused so loop can exit
                elif ch == '\x03':  # Ctrl+C
                    log.info("[QUIT] Ctrl+C received.")
                    self._stop.set()
                    self._paused.clear()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)  # always restore terminal