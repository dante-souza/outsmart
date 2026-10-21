"""
Bug: on Hugging Face, the first page load crashed while importing LiteLLM. During the import, LiteLLM attaches a
logging filter to the server's asyncio and uvicorn loggers, and that filter imports more of LiteLLM. When the server
logged while the script thread was still importing, the two threads deadlocked on Python's import locks.
Each check runs in a fresh interpreter, because LiteLLM is already imported in the test process.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

RACE = """
import logging, threading, time
server_logger = logging.getLogger("asyncio")
server_logger.addHandler(logging.NullHandler())
server_logger.propagate = False
outcome = []
errors = []

def script_thread():
    try:
        import interfaces.llms
        outcome.append("ok")
    except BaseException as e:
        outcome.append(type(e).__name__)

def log(message):
    try:
        server_logger.error(message)
    except BaseException as e:
        errors.append(type(e).__name__)

thread = threading.Thread(target=script_thread)
thread.start()
while thread.is_alive():
    log("Task exception was never retrieved")
    time.sleep(0.001)
for _ in range(5):
    log("logged after the import")
print(f"import {outcome[0]}, errors {sorted(set(errors))}")
"""


def test_importing_llms_while_the_server_logs_does_not_deadlock():
    env = {k: v for k, v in os.environ.items() if k != "LITELLM_DISABLE_REDACT_SECRETS"}
    result = subprocess.run(
        [sys.executable, "-c", RACE],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.stdout.strip() == "import ok, errors []", (
        result.stdout + result.stderr
    )
