"""
Standalone smoketest for the exact code path core/llm.py's LocalLLM
uses to reach Ollama's /api/chat -- run this directly from the
project's own virtual environment to prove (or disprove) that the
Python application can reach Ollama, independent of FastAPI/uvicorn
and independent of any specific agent.

Usage (from server/, with the project venv active):

    python tools\\ollama_chat_smoketest.py

Or on macOS/Linux:

    python tools/ollama_chat_smoketest.py

This does NOT reimplement the request -- it imports and calls the
real core.llm.LocalLLM class, so a pass here means the application's
actual HTTP client code works, not just that "some" Python script can
reach Ollama.

Exit code 0 = success (printed the model's real reply).
Exit code 1 = failure (printed exactly what failed and why).
"""

import sys
import os

# Allow running this script directly (python tools/ollama_chat_smoketest.py)
# from the server/ directory without needing to install the project
# as a package first.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm import LocalLLM, OLLAMA_HOST, OLLAMA_MODEL  # noqa: E402


def main():
    print(f"Target host:  {OLLAMA_HOST}")
    print(f"Target model: {OLLAMA_MODEL}")
    print(f"Final URL:    {OLLAMA_HOST}/api/chat")
    print("-" * 60)

    llm = LocalLLM()  # runs the same /api/tags reachability check as the real app

    print("-" * 60)
    print("Sending a minimal /api/chat request via LocalLLM.generate() ...")

    response_text = llm.generate(
        system_prompt="You are a helpful assistant.",
        user_prompt="hi",
        max_new_tokens=50,
    )

    print("-" * 60)
    if response_text:
        print("SUCCESS. Ollama responded:")
        print(response_text)
        return 0

    print(
        "FAILURE. LocalLLM.generate() returned an empty string, which "
        "means the request failed or Ollama returned no usable content "
        "-- check the '[LLM]' log lines printed above this line for the "
        "exact reason (non-200 status + response body, connection error, "
        "or unparseable JSON)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
