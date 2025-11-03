from PyQt5.QtCore import QThread, pyqtSignal
import time
import traceback

class ScriptRunner(QThread):
    status_signal = pyqtSignal(str)
    stats_signal = pyqtSignal(dict)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.start_time = 0
    def run(self):
        from main import run_main_script, log_queue
        try:
            self.start_time = time.time()
            self.status_signal.emit("运行中")
            run_main_script(enable_command_listener=True)
        except Exception as e:
            log_queue.put(f"脚本运行出错: {str(e)}")
            traceback.print_exc()
        finally:
            self.status_signal.emit("已停止")
            log_queue.put("===== 脚本运行结束 =====")
