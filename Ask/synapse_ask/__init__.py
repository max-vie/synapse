"""Synapse Ask package.

Public surface:
    APP_VERSION  – the current version string
    main         – CLI entry point (from cli.main)

Internal modules are importable but not re-exported here.
Import directly from the submodule you need, e.g.::

    from synapse_ask.formatting import display_answer_text
    from synapse_ask.tui_state import new_tui_state
"""

from .version import APP_VERSION
from .cli import main

__all__ = ["APP_VERSION", "main"]