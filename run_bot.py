#!/usr/bin/env python3
"""Arranca el bot en modo polling (desarrollo local)."""
import asyncio

from app.bot.main import run_polling

if __name__ == "__main__":
    try:
        asyncio.run(run_polling())
    except KeyboardInterrupt:
        pass
