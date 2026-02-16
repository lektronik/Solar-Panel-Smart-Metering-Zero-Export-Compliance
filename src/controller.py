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
        
        # Legacy specific params
        self.slow_approx_limit = ctrl.get("slow_approx_limit_percent", 0)
        self.slow_approx_factor = ctrl.get("slow_approx_factor_percent", 50)
        
        # We need max watt for percentage calculation in slow approx
        # But compute() receives max_watt.
        
        self.jump_percent = ctrl.on_grid_jump_percent
        self.fast_decrease = ctrl.fast_limit_decrease

        self._last_setpoint = 0
        self._prev_time = time.monotonic()

    def reset(self):
        self._last_setpoint = 0
        self._prev_time = time.monotonic()

    def compute(self, grid_watts: float, current_inverter_watts: float, max_watt: int, min_watt: int) -> int:
        """
        Tracked Integral Control:
        New Setpoint = _last_setpoint + adjustment
        But resets _last_setpoint to current_inverter_watts if we detect saturation (clouds).
        """
        error = grid_watts - self.target
        
        # 1. Check for Saturation / Drift
        # If we think we are at 1000W, but inverter is at 500W (and not ramping up?), we are drifting.
        # But inverter takes time to ramp.
        # Logic: If Current < Last * 0.8 (20% gap) AND we are trying to Increase?
        # Or just trust Current if it's very different?
        # Legacy script only did this if Previous >= Max.
        
        # Let's use a simpler heuristic:
        # If Current is significantly different from Last, and we have been stable for a bit?
        # Actually, simpler: Use _last_setpoint by default.
        # BUT if current_inverter_watts is significantly LOWER than _last_setpoint,
        # it means the inverter CANNOT reach the setpoint (Clouds).
        # In that case, use Current as the base.
        
        base_setpoint = self._last_setpoint
        
        if current_inverter_watts < (base_setpoint * 0.85):
             # Inverter is producing < 85% of what we asked. Likely drifting/saturated (Sun Limited).
             
             if error < 0:
                 # Exporting/Reducing.
                 # If we rely on 'base_setpoint' (which might be 1200W) to reduce to 0W export,
                 # and output is only 200W, we calculate new limit 1150W.
                 # Sending 1150W to a unit producing 200W does NOTHING.
                 # So we MUST reset base to Current (200W) to calculate drastic cut (e.g. 150W).
                 logger.info("Saturation & Export. Resetting base to current (%dW) for effective reduction.", int(current_inverter_watts))
                 base_setpoint = current_inverter_watts
             else:
                 # Importing (Error > 0).
                 # We want to increase power.
                 # If we reset base to Current (200W), new limit becomes 200+Error.
                 # It clamps the limit close to production.
                 # User wants UNLIMITED request if Sun Limited.
                 # So we keep 'base_setpoint' as is (e.g. 1200W or climbing).
                 logger.info("Saturation & Import. Maintaining base (%dW) to allow climbing to Max.", int(base_setpoint))
                 pass

        # Fast Response: Exporting (Grid < Min) -> Cut Immediately
        if grid_watts < self.min_point and self.fast_decrease:
            # Absolute correction: New = Base + Error
            setpoint = int(base_setpoint + error)
            setpoint = self._clamp(setpoint, min_watt, max_watt)
            logger.info(
                "FAST CUT: Grid %dW < %dW. Base %d -> %dW",
                int(grid_watts), self.min_point, int(base_setpoint), int(setpoint)
            )
            self._last_setpoint = setpoint
            return setpoint

        # Within tolerance?
        if abs(error) <= self.tolerance:
            return int(self._last_setpoint)

        # Normal Regulation Loop
        # Gain 1.0 to match legacy logic (We rely on 7s wait for stability)
        gain = 1.0
        
        # If very far off (Grid Spike), maybe higher gain?
        if grid_watts > self.max_point:
             # The original instruction had a syntax error here: `gain = 1.0(error * gain)`
             # Assuming the intent was to keep gain at 1.0 or apply it to adjustment.
             # Since the instruction was "Set Gain to 1.0 match legacy logic",
             # and the previous line already sets gain to 1.0, this conditional
             # block is removed to avoid ambiguity and maintain syntactic correctness.
             pass # No change to gain if grid_watts > self.max_point, as gain is already 1.0

        adjustment = int(error * gain)
        new_setpoint = int(base_setpoint + adjustment)
        
        # Slow Approximation Logic (Legacy Restoration)
        # Prevent rapid large drops which cause oscillation
        # Only applies when Reducing power (Error < 0)
        current_setpoint_diff = abs(base_setpoint - new_setpoint)
        slow_approx_limit_w = int(max_watt * self.slow_approx_limit / 100)
        
        if error < 0 and current_setpoint_diff > slow_approx_limit_w:
             # Reduce the adjustment magnitude
             # Legacy: new = new + (Diff * factor / 100)
             # Since Diff is positive, adding it moves new UP (less reduction).
             dampener = int(current_setpoint_diff * self.slow_approx_factor / 100)
             new_setpoint = new_setpoint + dampener
             logger.info("Slow Approx: Dampened reduction by %dW", dampener)

        # Clamp
        setpoint = self._clamp(new_setpoint, min_watt, max_watt)
        
        logger.info(
            "Regulating: Grid %dW (Err %d). Base %d -> %dW (Gain %.1f)",
            int(grid_watts), int(error), int(base_setpoint), int(setpoint), gain
        )
        
        self._last_setpoint = setpoint
        return setpoint

    @staticmethod
    def _clamp(value: int, low: int, high: int) -> int:
        return max(low, min(high, value))
