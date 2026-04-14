"""
XPERTIAL Agent

Usage:
    from xpertial import monitor
    monitor.start(api_key='YOUR_KEY')
"""

from .monitor import monitor, Monitor

__all__ = ["monitor", "Monitor"]
__version__ = "0.2.0"
