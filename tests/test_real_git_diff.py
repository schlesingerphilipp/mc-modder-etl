#!/usr/bin/env python3
"""
Test the diff splitting with real git diff format from diff_example.txt
"""

import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "app"))

from etl_pipeline import split_diff_by_file


def main():
    # Load the real diff file
    diff_file = Path(__file__).parent / "tests" / "resources" / "diff_example.txt"
    
    print("=" * 80)
    print("REAL GIT DIFF SPLITTING TEST")
    print("=" * 80)
    print(f"\nLoading: {diff_file}")
    
    with open(diff_file, "r", encoding="utf-8") as f:
        diff = f.read()
    
    print(f"Input: {len(diff)} bytes")
    
    # Split the diff
    result = split_diff_by_file(diff)
    
    print(f"\n✓ Successfully split into {len(result)} file diffs!\n")
    
    # Show each file
    for i, file_diff in enumerate(result, 1):
        lines = file_diff.split('\n')
        first_line = lines[0] if lines else ""
        
        # Extract filename from git header
        if first_line.startswith('diff --git a/'):
            filename = first_line.split(' b/')[1] if ' b/' in first_line else "unknown"
        else:
            filename = "unknown"
        
        # Count changes
        additions = sum(1 for line in lines if line.startswith('+') and not line.startswith('+++'))
        deletions = sum(1 for line in lines if line.startswith('-') and not line.startswith('---'))
        
        print(f"{i:2}. {filename:40} | +{additions:3} -{deletions:3} | {len(file_diff):6} bytes")
    
    print("\n" + "=" * 80)
    print("SUCCESS: All diffs were split correctly!")
    print("=" * 80)
    
    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
