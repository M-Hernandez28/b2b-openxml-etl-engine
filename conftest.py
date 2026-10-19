"""
conftest.py
-----------
Adds the repository root to sys.path so pytest can resolve
`src.*` and `sample_data.*` imports without a pip install -e step.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
