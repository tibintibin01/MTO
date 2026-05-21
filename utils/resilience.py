# -*- coding: utf-8 -*-
import time
from enum import Enum
from typing import Callable, Any, Optional
from utils.logger import mto_logger

class CircuitState(Enum):
    CLOSED = 0     # Normal operation
    HALF_OPEN = 1  # Testing if service is back
    OPEN = 2       # Failure mode - immediate rejection

class CircuitBreaker:
    """
    Industrial Circuit Breaker to prevent cascading failures in Municipal Infrastructure.
    """
    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.last_failure_time = 0
        
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Executes the protected function, managing circuit state transitions.
        """
        # 1. Check if we should attempt recovery
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                mto_logger.info(f"Circuit {self.name} is now HALF-OPEN. Testing recovery...")
            else:
                # Fail-Fast: Reject the call immediately
                raise RuntimeError(f"Circuit {self.name} is OPEN. Resilience rejection triggered.")
        
        try:
            # 2. Attempt the actual operation
            result = func(*args, **kwargs)
            
            # 3. Success: Reset if we were failing
            if self.state != CircuitState.CLOSED:
                mto_logger.info(f"Circuit {self.name} has recovered and is now CLOSED.")
            
            self.state = CircuitState.CLOSED
            self.failures = 0
            return result
            
        except Exception as e:
            # 4. Failure: Track and potentially trip
            self.failures += 1
            self.last_failure_time = time.time()
            
            if self.failures >= self.failure_threshold:
                if self.state != CircuitState.OPEN:
                    mto_logger.critical(f"Circuit {self.name} TRIPPED! Status changed to OPEN. Consecutive failures: {self.failures}")
                self.state = CircuitState.OPEN
            
            # Re-raise so the caller can handle the specific error (or use fallback)
            raise

    def get_state_numeric(self) -> int:
        """Returns numeric state for Prometheus telemetry."""
        return self.state.value
