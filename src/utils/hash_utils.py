"""
Hash utility functions for file operations.

This module provides common hash calculation functions used throughout the application.
"""

import hashlib
from pathlib import Path


def calculate_file_hash(file_path: str, include_filename: bool = True) -> str:
    """
    Calculate SHA-256 hash of a file, optionally including the filename.

    Args:
        file_path: Path to the file
        include_filename: Whether to include the filename in the hash calculation

    Returns:
        SHA-256 hash as hexadecimal string, or empty string on error
    """
    try:
        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            return ""

        if not file_path_obj.is_file():
            return ""

        with open(file_path, 'rb') as f:
            file_hash = hashlib.sha256()

            # Include filename in hash for uniqueness if requested
            if include_filename:
                filename = file_path_obj.name
                file_hash.update(filename.encode('utf-8'))

            chunk = f.read(8192)
            while chunk:
                file_hash.update(chunk)
                chunk = f.read(8192)

            return file_hash.hexdigest()

    except (OSError, IOError, Exception):
        return ""


def calculate_screenshot_hash(file_path: str) -> str:
    """
    Calculate SHA-256 hash of a screenshot file including filename.

    This is a convenience function specifically for screenshot files
    that always includes the filename in the hash calculation.

    Args:
        file_path: Path to the screenshot file

    Returns:
        SHA-256 hash as hexadecimal string
    """
    return calculate_file_hash(file_path, include_filename=True)
