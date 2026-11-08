"""Compatibility entry point for baseline-only shared evaluation."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.scripts.run_evaluation import main

if __name__ == '__main__':
    main(['--systems', 'baseline'] + sys.argv[1:])
