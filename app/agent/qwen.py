"""Qwen2.5-0.5B-Instruct through `transformers`.

Not installed by default, on purpose: the package is torch plus a checkpoint
(~1 GB), which has no business in `requirements.txt` for a feature that is off
until somebody turns it on. Install it with:

    pip install -r requirements-agent.txt

Weights come from the Hugging Face hub on first use (`AGENT_MODEL_ID`) unless
`AGENT_MODEL_PATH` points at a local copy, which is what an offline or
bundle-limited host needs.

Import of `torch`/`transformers` is deferred to first use, because this module is
imported on every `resolve_backend()` — the agent being off must cost nothing.
The 0.5B checkpoint needs no GPU: it answers in a few seconds on CPU.
"""

import asyncio
import threading
from typing import Any, Optional, Sequence

from app.agent.backend import AgentUnavailable, ChatMessage

DEFAULT_MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"

_INSTALL_HINT = (
    "the agent model is not installed: run `pip install -r requirements-agent.txt` "
    "in the API environment and restart the API"
)


def missing_dependencies() -> Optional[str]:
    """Why the runtime is unusable, or `None` when both libraries import."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return _INSTALL_HINT
    return None


class QwenBackend:
    """Runs one checkpoint in this process, one generation at a time."""

    name = "qwen"

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        model_path: str = "",
        device: str = "cpu",
        temperature: float = 0.2,
    ) -> None:
        self.model = model_id
        # `model_path` is a filesystem path and never leaves this object: the
        # status endpoint reports `model` (the id), not the directory.
        self._source = model_path or model_id
        self._device = device or "cpu"
        self._temperature = max(0.0, temperature)
        self._load_lock = threading.Lock()
        self._generate_lock = asyncio.Lock()
        self._model: Any = None
        self._tokenizer: Any = None

    # --- availability -----------------------------------------------------

    def unavailable_reason(self) -> Optional[str]:
        return missing_dependencies()

    def _load(self):
        """Load the checkpoint once, under a lock; both halves or neither."""
        if self._model is not None:
            return self._model, self._tokenizer

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        with self._load_lock:
            if self._model is None:
                self._tokenizer = AutoTokenizer.from_pretrained(self._source)
                self._model = AutoModelForCausalLM.from_pretrained(
                    self._source,
                    dtype=(
                        torch.bfloat16
                        if self._device.startswith("cuda")
                        else torch.float32
                    ),
                ).to(self._device)
                self._model.eval()
        return self._model, self._tokenizer

    # --- generation -------------------------------------------------------

    async def complete(
        self, messages: Sequence[ChatMessage], *, max_new_tokens: int
    ) -> str:
        reason = self.unavailable_reason()
        if reason is not None:
            raise AgentUnavailable(reason)

        # `generate` is blocking C work: run it off the event loop, and serialise
        # it so two chats cannot multiply the memory of one checkpoint (each
        # worker process holds its own copy — see docs/DEPLOYMENT.md).
        async with self._generate_lock:
            return await asyncio.to_thread(self._generate, list(messages), max_new_tokens)

    def _generate(self, messages: list[ChatMessage], max_new_tokens: int) -> str:
        import torch

        model, tokenizer = self._load()
        conversation = [{"role": m.role, "content": m.content} for m in messages]
        prompt = tokenizer.apply_chat_template(
            conversation, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(self._device)

        options: dict[str, Any] = {
            "max_new_tokens": max(1, max_new_tokens),
            "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
        }
        if self._temperature > 0:
            options.update(do_sample=True, temperature=self._temperature, top_p=0.9)
        else:
            options["do_sample"] = False

        with torch.inference_mode():
            generated = model.generate(**inputs, **options)

        # `generate` returns the prompt followed by the continuation.
        continuation = generated[0][inputs["input_ids"].shape[-1] :]
        return tokenizer.decode(continuation, skip_special_tokens=True).strip()
