#!/usr/bin/env python3
"""
KneeSpa Application Entry Point
This is the main entry point for the KneeSpa application.
"""
import sys
from main.modules.core.app import run_application

if __name__ == "__main__":
    sys.exit(run_application())