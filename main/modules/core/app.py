"""
Application Entry Point Module
Provides the main application setup and entry point
"""
import os
import sys
import argparse
import logging

from main.modules.utils.logging_utils import setup_logger, capture_exceptions
from main.modules.utils.performance_metrics import system_metrics
from main.modules.core.services import get_container
from main.config.settings import load_settings, get_settings
from main.config.constants import APP_NAME, APP_VERSION

def setup_application(debug_mode: bool = False):
    """
    Set up the application
    
    Args:
        debug_mode: Whether to run in debug mode
        
    Returns:
        Tuple of (container, logger)
    """
    # Load settings
    load_settings()
    settings = get_settings()
    
    # Setup logging
    log_level = logging.DEBUG if debug_mode else logging.INFO
    logger = setup_logger(
        name=APP_NAME,
        level=log_level,
        log_to_console=True,
        use_json=True,
        log_metrics=True
    )
    
    # Start system metrics collection
    if settings.get("collect_metrics", True):
        system_metrics.start()
        logger.info("System metrics collection started")
    
    # Set up global exception handler
    capture_exceptions(logger)
    
    # Set up dependency injection container
    container = get_container(debug_mode)
    
    logger.info(
        f"Application initialized",
        structured_data={
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "debug_mode": debug_mode,
            "config_file": settings.get("config_file", "default")
        }
    )
    
    return container, logger

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{APP_VERSION}")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    
    args = parser.parse_args()
    
    if args.version:
        print(f"{APP_NAME} v{APP_VERSION}")
        sys.exit(0)
        
    return args

def run_application():
    """Run the application"""
    args = parse_args()
    
    # Set config file if provided
    if args.config:
        os.environ["KNEESPA_CONFIG"] = args.config
    
    # Set up application
    container, logger = setup_application(args.debug)
    
    try:
        # Get UI controller
        ui_controller = container.resolve("ui_controller")
        
        # Start UI
        logger.info("Starting UI...")
        ui_controller.start()
        
        # Clean up
        system_metrics.stop()
        logger.info("Application exiting normally")
        
    except Exception as e:
        logger.critical(
            f"Application error",
            structured_data={"error": str(e)},
            exc_info=True
        )
        system_metrics.stop()
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(run_application())