import pytest
from unittest.mock import MagicMock
from src.controller import ZeroExportController
from src.config import Config

@pytest.fixture
def mock_config():
    data = {
        "control": {
            "target_point_w": 20,
            "tolerance_w": 10,
            "max_point_w": 5000,
            "min_point_w": -5000,
            "slow_approx_limit_percent": 10,
            "slow_approx_factor_percent": 50,
            "on_grid_jump_percent": 20,
            "fast_limit_decrease": True,
            "loop_interval_s": 1,
            "set_limit_timeout_s": 5,
        }
    }
    return Config(data)

@pytest.fixture
def controller(mock_config):
    return ZeroExportController(mock_config)

def test_initial_state(controller):
    assert controller._last_setpoint == 0

def test_normal_regulation_import(controller):
    # Setup: Base setpoint 1000W. Grid 500W. Target 20W.
    # Error = 480. Expected increase.
    controller._last_setpoint = 1000
    
    # Grid 500W, Inverter 1000W (matching base), Max 2000W, Min 100W
    new_setpoint = controller.compute(
        grid_watts=500, 
        current_inverter_watts=1000, 
        max_watt=2000, 
        min_watt=100
    )
    
    # new = 1000 + (500 - 20) = 1480
    assert new_setpoint == 1480
    assert controller._last_setpoint == 1480

def test_normal_regulation_export(controller):
    # Setup: Base 1000W. Grid -200W. Target 20W.
    # Error = -220. Expected decrease.
    controller._last_setpoint = 1000
    
    new_setpoint = controller.compute(
        grid_watts=-100, 
        current_inverter_watts=1000, 
        max_watt=2000, 
        min_watt=0
    )
    
    # new = 1000 + (-100 - 20) = 880
    # Diff = 120. Limit = 200. No dampening.
    assert new_setpoint == 880

def test_saturation_export(controller):
    # Setup: Base 1000W. Inverter 200W (Drifting/Clouds).
    # Grid -100W (Exporting). Target 20W. Error = -120.
    
    controller._last_setpoint = 1000
    
    # If we used base 1000, new would be 880 (no effect on 200W output).
    # Should reset base to 200. New = 200 - 120 = 80.
    
    new_setpoint = controller.compute(
        grid_watts=-100, 
        current_inverter_watts=200, 
        max_watt=2000, 
        min_watt=0
    )
    
    assert new_setpoint == 80

def test_saturation_import_no_reset(controller):
    # Setup: Base 1000W. Inverter 200W.
    # Grid 500W (Importing). Target 20W. Error = 480.
    
    controller._last_setpoint = 1000
    
    # Logic says: If importing, we want to climb. Don't reset base.
    # New = 1000 + 480 = 1480.
    
    new_setpoint = controller.compute(
        grid_watts=500, 
        current_inverter_watts=200, 
        max_watt=2000, 
        min_watt=0
    )
    
    assert new_setpoint == 1480

def test_fast_response_cut(controller):
    # Config ensures fast_decrease is True.
    # Grid -6000 (Very high export). Min point -5000.
    # Should trigger FAST CUT.
    
    controller._last_setpoint = 2000
    
    new_setpoint = controller.compute(
        grid_watts=-6000, 
        current_inverter_watts=2000, 
        max_watt=2000, 
        min_watt=0
    )
    
    # Error = -6000 - 20 = -6020
    # New = 2000 - 6020 = -4020 -> Clamped to 0
    assert new_setpoint == 0

def test_slow_approximation(controller):
    # Error < 0. Diff > slow_approx_limit.
    # Max watt 2000. Limit 10% = 200W.
    # Factor 50%.
    
    controller._last_setpoint = 1000
    
    # Grid -500. Target 20. Error -520.
    # Raw new = 480. Diff = 520.
    # Diff 520 > Limit 200.
    # Dampener = 520 * 0.5 = 260.
    # Adjusted new = 480 + 260 = 740.
    
    new_setpoint = controller.compute(
        grid_watts=-500,
        current_inverter_watts=1000, 
        max_watt=2000, 
        min_watt=0
    )
    
    assert new_setpoint == 740

def test_tolerance(controller):
    # Error within tolerance (10W).
    controller._last_setpoint = 500
    
    new_setpoint = controller.compute(
        grid_watts=25, # Error 5
        current_inverter_watts=500, 
        max_watt=2000, 
        min_watt=0
    )
    
    assert new_setpoint == 500
