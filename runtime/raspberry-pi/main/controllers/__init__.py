# controllers/
"""Behavior modules extracted from the KneeSpa window class.

Each controller owns one responsibility and operates on the main window
through composition; the window keeps thin delegating slots so all Qt
signal wiring is unchanged. This makes the logic unit-testable against
a stub window (the 2,500-line god class had 0% coverage on exactly the
safety-critical paths).
"""
