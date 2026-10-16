"""The findings agent: a chat that explains what the analyzers reported.

The model is deliberately *not* a platform dependency. Everything above
`app/agent/backend.py` is written against the `AgentBackend` protocol, so
installing Qwen2.5-0.5B-Instruct (`pip install -r requirements-agent.txt`) turns
the chat on without touching the endpoints, the prompt builder or the SPA. Until
then `resolve_backend()` reports why it cannot run and `/api/v1/agent/status`
says so — a request never gets an invented explanation.

Layout:

* `backend.py`    — the seam (`AgentBackend`, `ChatMessage`) and `AgentUnavailable`
* `qwen.py`       — the local transformers implementation of that seam
* `cloudflare.py` — the hosted Workers AI implementation of that seam
* `prompt.py`     — findings → bounded conversation (pure, testable)
* `registry.py`   — which backend the settings ask for
* `service.py`    — ownership, findings reads and one generation call
"""
