import time
import datetime
from typing import Any, Dict, List
from langchain_core.callbacks import AsyncCallbackHandler

class TimingCallbackHandler(AsyncCallbackHandler):
    """
    A custom callback handler that tracks the execution times of tools and the LLM.
    It logs them to the console and stores them to be retrieved by the Streamlit UI.
    """
    def __init__(self):
        super().__init__()
        self.timings = []
        self.starts = {}

    async def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        """Run when LLM starts running."""
        run_id = kwargs.get("run_id")
        self.starts[run_id] = time.perf_counter()
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 🤖 LLM started thinking...")

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """Run when LLM ends running."""
        run_id = kwargs.get("run_id")
        start_time = self.starts.pop(run_id, None)
        if start_time:
            duration = time.perf_counter() - start_time
            msg = f"🤖 LLM responded in {duration:.2f}s"
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
            self.timings.append(msg)

    async def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        """Run when tool starts running."""
        name = serialized.get("name", "tool")
        run_id = kwargs.get("run_id")
        self.starts[run_id] = time.perf_counter()
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 🛠️ Tool '{name}' started...")

    async def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        """Run when tool ends running."""
        name = kwargs.get("name", "tool")
        run_id = kwargs.get("run_id")
        start_time = self.starts.pop(run_id, None)
        if start_time:
            duration = time.perf_counter() - start_time
            msg = f"🛠️ Tool '{name}' finished in {duration:.2f}s"
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
            self.timings.append(msg)
