#!/usr/bin/env python
"""
Main entry point for Generator Booking Ledger.
Routes to either web interface or CLI based on arguments.
"""

import sys
import argparse
import logging
from pathlib import Path

# Setup logging
from config import setup_logging, HOST, PORT
setup_logging()

logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generator Booking Ledger - Database management system"
    )
    
    parser.add_argument(
        '--cli',
        action='store_true',
        help='Run in command-line mode (default is web)'
    )
    
    parser.add_argument(
        '--web',
        action='store_true',
        default=True,
        help='Run web interface (default)'
    )
    
    parser.add_argument(
        '--host',
        default=HOST,
        help=f'Host for web server (default: {HOST})'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=PORT,
        help=f'Port for web server (default: {PORT})'
    )
    
    args = parser.parse_args()
    
    if args.cli:
        # Run CLI
        logger.info("Starting CLI mode")
        from cli import CLI
        cli = CLI()
        try:
            cli.run()
        except KeyboardInterrupt:
            print("\n\nExiting...")
            logger.info("CLI exited by user")
    else:
        # Run web server
        logger.info(f"Starting web server on {args.host}:{args.port}")
        import uvicorn
        from web.app import app
        
        print(f"\n🚀 Starting Generator Booking Ledger Web Server")
        print(f"📍 Server: http://{args.host}:{args.port}")
        print(f"📖 API Docs: http://{args.host}:{args.port}/docs")
        print(f"🛑 Press Ctrl+C to stop\n")
        
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info"
        )


if __name__ == "__main__":
    main()
