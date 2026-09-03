"""Lightweight in-process scheduler for optional monitoring checks.

This is intentionally not distributed and does not replace the manual check.
It periodically asks the schedule store for due services and delegates the
actual Monitoring/Alert logic to the same callback used by the API endpoint.
"""
import threading


class MonitoringScheduler:
    def __init__(self, schedule_store, run_callback, poll_seconds=60):
        self.schedule_store = schedule_store
        self.run_callback = run_callback
        self.poll_seconds = max(1, int(poll_seconds))
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def run_due_once(self):
        for schedule in self.schedule_store.list_due():
            try:
                self.run_callback(schedule)
            except Exception:
                # Keep the small scheduler alive if one service cannot be
                # checked. The next configured interval will retry it.
                pass
            finally:
                # A failed run is advanced as well so one broken service cannot
                # cause a tight retry loop.
                self.schedule_store.mark_run(schedule["id"], schedule["frequency"])

    def _loop(self):
        while not self._stop.wait(self.poll_seconds):
            self.run_due_once()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="zxr-monitoring-scheduler", daemon=True
            )
            self._thread.start()

    def stop(self):
        self._stop.set()
