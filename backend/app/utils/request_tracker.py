"""Request tracking and logging utilities."""

import logging
import time
import uuid
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class RequestTracker:
    """Track request execution with request_id and step timing."""

    def __init__(self, request_id: Optional[str] = None):
        self.request_id = request_id or generate_request_id()
        self.start_time = time.time()
        self.step_times = {}
        self.logs = []
        self._step_start_time = None

    def log(self, message: str, level: str = "INFO"):
        """Log message with request_id prefix."""
        log_msg = f"[{self.request_id}] {message}"
        self.logs.append(log_msg)

        if level == "ERROR":
            logger.error(log_msg)
        elif level == "WARNING":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    def start_step(self, step_name: str):
        """Mark start of a step."""
        self._step_start_time = time.time()
        self.log(f"Starting: {step_name}")

    def end_step(self, step_name: str, success: bool = True, error: Optional[str] = None):
        """Mark end of a step."""
        if self._step_start_time:
            duration_ms = int((time.time() - self._step_start_time) * 1000)
            self.step_times[step_name] = {
                "status": "SUCCESS" if success else "FAILED",
                "duration_ms": duration_ms,
                "error": error,
            }
            status_str = "FAILED" if error else "SUCCESS"
            self.log(f"Completed: {step_name} ({duration_ms}ms) - {status_str}")

    def get_total_duration_ms(self) -> int:
        """Get total execution time in milliseconds."""
        return int((time.time() - self.start_time) * 1000)

    def get_logs(self) -> list[str]:
        """Get all logs collected."""
        return self.logs


def generate_request_id() -> str:
    """Generate unique request ID."""
    timestamp = int(datetime.now().timestamp())
    unique = str(uuid.uuid4())[:8]
    return f"req-{timestamp}-{unique}"
