"""Compatibility import; deployed adapter lives in app/mollie_payments.py."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from mollie_payments import *
