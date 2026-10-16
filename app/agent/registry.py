"""Which backend the settings ask for.

The single place that maps configuration onto an implementation. Adding a
runtime (a quantised build, a hosted endpoint, a second checkpoint) means adding
a branch here and nothing else — the endpoints and the prompt builder only ever
see `AgentBackend`.
"""

from app.agent.backend import AgentBackend, UnavailableBackend
from app.agent.cloudflare import CloudflareBackend
from app.agent.qwen import QwenBackend
from app.core.config import settings

#: Backends this build knows how to construct.
KNOWN_BACKENDS = ("qwen", "cloudflare", "none")


def resolve_backend() -> AgentBackend:
    """The configured backend.

    Never raises for a configuration problem: an unknown name or a disabled
    agent becomes an `UnavailableBackend`, whose `unavailable_reason()` is what
    `/api/v1/agent/status` reports and what turns a chat request into a 503.
    A `qwen` backend whose libraries are missing is returned as-is — it carries
    the install hint itself.

    `cloudflare` is the other way round: it needs no local install, so its
    availability is decided entirely by whether its two settings are set.
    """
    name = (settings.AGENT_BACKEND or "none").strip().lower()

    if name == "none":
        return UnavailableBackend(
            name="none",
            model="",
            reason="the findings agent is disabled (AGENT_BACKEND=none)",
        )

    if name == "qwen":
        return QwenBackend(
            model_id=settings.AGENT_MODEL_ID,
            model_path=settings.AGENT_MODEL_PATH,
            device=settings.AGENT_DEVICE,
            temperature=settings.AGENT_TEMPERATURE,
        )

    if name == "cloudflare":
        # Nothing to install and nothing to load: this one either has credentials
        # or reports the settings that are missing.
        return CloudflareBackend(
            account_id=settings.CLOUDFLARE_ACCOUNT_ID,
            api_token=settings.CLOUDFLARE_API_TOKEN,
            model_id=settings.CLOUDFLARE_MODEL_ID,
            temperature=settings.AGENT_TEMPERATURE,
            timeout=settings.AGENT_TIMEOUT_SECONDS,
        )

    return UnavailableBackend(
        name=name, model="", reason=f"unknown agent backend '{name}'"
    )
