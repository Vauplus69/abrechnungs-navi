"""Compatibility import for the deployed document module."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from document_extraction import *
