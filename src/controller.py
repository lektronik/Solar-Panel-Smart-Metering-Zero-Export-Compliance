import logging
import time

from src.config import Config

logger = logging.getLogger(__name__)


class ZeroExportController:
    def __init__(self, cfg: Config):
        ctrl = cfg.control
        self.target = ctrl.target_point_w
        self.tolerance = ctrl.tolerance_w
        self.max_point = ctrl.max_point_w
        self.min_point = ctrl.min_point_w
        
        # New parameters for "Slow Approximation" (Legacy Logic)
        self.slow_approx_limit = ctrl.get("slow_approx_limit_percent", 50)  # Default 50%
        self.slow_approx_factor = ctrl.get("slow_approx_factor_percent", 50) # Default 50%
        
        self.jump_percent = ctrl.on_grid_jump_percent
        self.fast_decrease = ctrl.fast_limit_decrease

        self._last_setpoint = 0
        self._prev_time = time.monotonic()

    def reset(self):
        self._last_setpoint = 0
        self._prev_time = time.monotonic()

    def compute(self, grid_watts: float, max_watt: int, min_watt: int) -> int:
        # Effective error = grid_watts - target
        error = grid_watts - self.target
        
        # Fast response: grid consumption spike (Importing > max_point)
        if grid_watts > self.max_point:
            if self.jump_percent > 0:
                jump_target = int(max_watt * self.jump_percent / 100)
                # If jumping, ensure we increase at least to match current import + previous setpoint
                setpoint = max(jump_target, self._last_setpoint + int(error))
            else:
                setpoint = self._last_setpoint + int(error)
                
            setpoint = self._clamp(setpoint, min_watt, max_watt)
            self._last_setpoint = setpoint
            logger.info(
                "Grid spike %dW > max %dW → fast increase to %dW",
                int(grid_watts), self.max_point, setpoint,
            )
            return setpoint

        # Fast response: overfeeding the grid (Exporting < min_point)
        if grid_watts < self.min_point and self.fast_decrease:
            setpoint = self._last_setpoint + int(error)
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

        # Normal Regulation Loop (Integral Action)
        new_setpoint = self._last_setpoint + int(error)
        
        # "Slow Approximation" Dampening Logic
        # Used to smoothen the curve when reducing power (overproduction)
        slow_approx_limit_w = int(max_watt * self.slow_approx_limit / 100)
        limit_diff = abs(self._last_setpoint - new_setpoint)
        
        if limit_diff > slow_approx_limit_w:
            # Only apply if reducing power (error < 0)
            if error < 0: 
                dampener = int(limit_diff * self.slow_approx_factor / 100)
                # logic: add dampener back to increase it slightly (less reduction)
                # new_setpoint was reduced. Adding makes it closer to previous.
                new_setpoint = new_setpoint + dampener
                logger.debug(f"Slow approx: dampened reduction by {dampener}W")
        
        setpoint = self._clamp(new_setpoint, min_watt, max_watt)
        
        if grid_watts < self.target - self.tolerance:
            logger.info(
                "Overproducing: grid=%dW, target=%dW → limit %dW (Integral + Dampening)",
                int(grid_watts), self.target, setpoint
            )
        else:
            logger.info(
                "Underproducing: grid=%dW, target=%dW → limit %dW",
                int(grid_watts), self.target, setpoint
            )

        self._last_setpoint = setpoint
        return setpoint

    @staticmethod
    def _clamp(value: int, low: int, high: int) -> int:
        return max(low, min(high, value))
