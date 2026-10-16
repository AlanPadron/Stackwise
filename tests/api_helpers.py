"""Driving the repository import from an API test.

A run only ever comes from `POST /projects/from-repo` now, so every test that
needs one goes through the two steps wrapped here: ask for the import, then wait
for its run to leave the pending/running states.
"""

import asyncio

IMPORT_URL = "/api/v1/projects/from-repo"
TERMINAL_STATUSES = ("completed", "completed_with_errors", "failed", "cancelled")


async def import_repository(client, headers, *, repository="octocat/demo", **payload):
    """POST one import and hand back the raw response (statuses vary by test)."""
    return await client.post(
        IMPORT_URL, json={"repository": repository, **payload}, headers=headers
    )


async def wait_for_run(client, headers, run_id, *, attempts: int = 40) -> dict:
    """Poll one run until it reaches a terminal status."""
    for _ in range(attempts):
        run = (await client.get(f"/api/v1/analyses/{run_id}", headers=headers)).json()
        if run["status"] in TERMINAL_STATUSES:
            return run
        await asyncio.sleep(0.05)
    raise AssertionError(f"run never finished: {run_id}")


async def import_and_wait(client, headers, *, repository="octocat/demo", **payload):
    """Import a repository and return `(project, run)` with the run finished."""
    response = await import_repository(client, headers, repository=repository, **payload)
    assert response.status_code == 201, response.text
    body = response.json()
    return body["project"], await wait_for_run(client, headers, body["run"]["id"])
