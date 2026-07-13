"""Own the QThread bridge while keeping visual state in the main window."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ...worker import WorkerThread


class RunController(QObject):
    completed = Signal()
    failed = Signal(str)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.worker: WorkerThread | None = None

    @property
    def is_active(self):
        return self.engine.is_running or bool(self.worker and self.worker.isRunning())

    def start(
        self,
        tasks,
        log_callback,
        status_callback,
        click_callback,
        debug_callback=None,
    ):
        if self.is_active:
            return False, "已有脚本正在运行"
        run_id = self.engine.reserve_run()
        if run_id is None:
            return False, "执行引擎正忙"
        try:
            worker = WorkerThread(self.engine, tasks, run_id)
            worker.log_signal.connect(log_callback)
            worker.status_signal.connect(status_callback)
            worker.click_signal.connect(click_callback)
            if debug_callback is not None:
                worker.debug_signal.connect(debug_callback)
            worker.error_signal.connect(self.failed)
            worker.finished.connect(self._on_finished)
            self.worker = worker
            worker.start()
            return True, ""
        except Exception as error:
            self.engine.finish_run(run_id, "start_failed", str(error))
            self.worker = None
            return False, str(error)

    def stop(self):
        return self.engine.stop()

    def pause_at_next_step(self):
        return self.engine.debug_session.request_pause()

    def continue_run(self):
        return self.engine.debug_session.continue_run()

    def step_over(self):
        return self.engine.debug_session.step_over()

    def _on_finished(self):
        self.completed.emit()
