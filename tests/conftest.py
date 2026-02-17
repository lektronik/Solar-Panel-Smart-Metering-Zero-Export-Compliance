import os
import sys
import pytest
from pathlib import Path

# Ensure src is in pythonpath
sys.path.insert(0, str(Path(__file__).parent.parent))

@pytest.fixture
def mock_env():
    """Context manager to safely mock env vars"""
    old_environ = os.environ.copy()
    try:
        yield os.environ
    finally:
        os.environ.clear()
        os.environ.update(old_environ)
