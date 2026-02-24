#!/usr/bin/env python3
"""
Test the diff splitting with real git diff format from diff_example.txt
"""

import sys
from pathlib import Path
from app.git_data.etl_pipeline import split_diff_by_file


def main():
    # Test with a real git diff example, and manually verified output
    diff_file = Path(__file__) / "resources" / "diff_example_input.txt"
    with open(diff_file, "r", encoding="utf-8") as f:
        diff = f.read()
    # Split the diff
    result = split_diff_by_file(diff)
    expected_1 = Path(__file__) / "resources" / "diff_example_output_1.txt"
    expected_2 = Path(__file__) / "resources" / "diff_example_output_2.txt"
    assert len(result) == 2, f"Expected 2 file diffs, got {len(result)}"
    assert result[0].strip() == expected_1.read_text(encoding="utf-8").strip(), "First file diff does not match expected output"
    assert result[1].strip() == expected_2.read_text(encoding="utf-8").strip(), "Second file diff does not match expected output"