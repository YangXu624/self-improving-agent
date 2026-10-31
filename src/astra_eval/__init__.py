"""Simulated-shopper evaluation harness for ASTRA.

Isolation rule: the shopping application (`shopping_agent`) never imports this package, the
simulated shopper only ever sees its own profile and the visible conversation, and ground
truth is loaded only by the scorer and the runner's audit checks.
"""

VERSION = "eval-v1"
