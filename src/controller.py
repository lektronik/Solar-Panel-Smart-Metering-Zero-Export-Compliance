import logging
import time

from src.config import Config

logger = logging.getLogger(__name__)


class PIDController:
    def __init__(self, cfg: Config):
        ctrl = cfg.control
        self.target = ctrl.target_point_w
        self.tolerance = ctrl.tolerance_w
        self.max_point = ctrl.max_point_w
        self.min_point = ctrl.min_point_w
        self.kp = ctrl.kp
        self.ki = ctrl.ki
        self.kd = ctrl.kd
        self.integral_max = ctrl.integral_max
        self.jump_percent = ctrl.on_grid_jump_percent
        self.fast_decrease = ctrl.fast_limit_decrease

        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_time = time.monotonic()
        self._last_setpoint = 0

    def reset(self):
        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_time = time.monotonic()

    def compute(self, grid_watts: float, max_watt: int, min_watt: int) -> int:
        error = grid_watts - self.target
        now = time.monotonic()
        dt = now - self._prev_time
        self._prev_time = now

        if dt <= 0:
            dt = 0.1

        # Fast response: grid consumption spike
        if grid_watts > self.max_point:
            if self.jump_percent > 0:
                jump_target = int(max_watt * self.jump_percent / 100)
                setpoint = max(jump_target, self._last_setpoint + int(error))
            else:
                setpoint = self._last_setpoint + int(error)
            self._integral = 0.0
            setpoint = self._clamp(setpoint, min_watt, max_watt)
            self._last_setpoint = setpoint
            logger.info(
                "Grid spike %dW > max %dW → fast increase to %dW",
                int(grid_watts), self.max_point, setpoint,
            )
            return setpoint

        # Fast response: overfeeding the grid
        if grid_watts < self.min_point and self.fast_decrease:
            setpoint = self._last_setpoint + int(error)
            self._integral = 0.0
            setpoint = self._clamp(setpoint, min_watt, max_watt)
            self._last_setpoint = setpoint
            logger.info(
                "Grid feed %dW < min %dW → fast decrease to %dW",
                int(grid_watts), self.min_point, setpoint,
            )
            return setpoint

        # Within tolerance band — no action needed
        if abs(error) <= self.tolerance:
            return self._last_setpoint

        # PID calculation
        self._integral += error * dt
        self._integral = max(-self.integral_max, min(self.integral_max, self._integral))

        derivative = (error - self._prev_error) / dt
        self._prev_error = error

        adjustment = self.kp * error + self.ki * self._integral + self.kd * derivative
        setpoint = self._last_setpoint + int(adjustment)
        setpoint = self._clamp(setpoint, min_watt, max_watt)

        if grid_watts < self.target - self.tolerance:
            logger.info(
                "Overproducing: grid=%dW, target=%dW → limit %dW (P=%.1f I=%.1f D=%.1f)",
                int(grid_watts), self.target, setpoint,
                self.kp * error, self.ki * self._integral, self.kd * derivative,
            )
        else:
            logger.info(
                "Underproducing: grid=%dW, target=%dW → limit %dW (P=%.1f I=%.1f D=%.1f)",
                int(grid_watts), self.target, setpoint,
                self.kp * error, self.ki * self._integral, self.kd * derivative,
            )

        self._last_setpoint = setpoint
        return setpoint

    @staticmethod
    def _clamp(value: int, low: int, high: int) -> int:
        return max(low, min(high, value))
