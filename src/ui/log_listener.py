from PyQt5.QtCore import QThread, pyqtSignal
import time

class LogListener(QThread):
    log_signal = pyqtSignal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = True
    def run(self):
        from main import log_queue
        while self.running:
            try:
                while not log_queue.empty():
                    log = log_queue.get_nowait()
                    self.log_signal.emit(log)
                time.sleep(0.1)
            except Exception as e:
                print(f"日志监听异常: {str(e)}")
    def stop(self):
        self.running = False
