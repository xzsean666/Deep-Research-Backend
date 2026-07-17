import asyncio
import logging

from app.services.worker import run_worker_loop

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker_loop())
