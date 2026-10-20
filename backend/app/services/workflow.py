"""Explicit video-project state machine."""

from datetime import UTC, datetime

from app.core.errors import InvalidStateError
from app.models import VideoProject
from app.models.enums import ProjectStatus as S

TERMINAL = {S.FAILED, S.CANCELLED, S.PUBLISHED}

ALLOWED: dict[S, set[S]] = {
    S.PENDING: {S.RESEARCHING, S.SCRIPTING, S.GENERATING_MEDIA},
    S.RESEARCHING: {S.SCRIPTING},
    S.SCRIPTING: {S.GENERATING_MEDIA, S.PENDING},
    S.GENERATING_MEDIA: {S.RENDERING},
    S.RENDERING: {S.VALIDATING},
    S.VALIDATING: {S.READY},
    S.READY: {S.UPLOADING, S.GENERATING_MEDIA},
    S.UPLOADING: {S.SCHEDULED, S.PUBLISHED, S.READY},
    S.SCHEDULED: {S.PUBLISHED, S.READY},
    S.PUBLISHED: set(),
    # Safe retries: a failed/cancelled project restarts from the step that failed (or from media generation).
    S.FAILED: {S.SCRIPTING, S.GENERATING_MEDIA, S.READY, S.UPLOADING},
    S.CANCELLED: {S.SCRIPTING, S.GENERATING_MEDIA, S.READY},
}


def can_transition(current: S, target: S) -> bool:
    if target in (S.FAILED, S.CANCELLED):
        return current not in TERMINAL or current == S.FAILED and target == S.CANCELLED
    return target in ALLOWED.get(current, set())


def transition(project: VideoProject, target: S, note: str | None = None) -> None:
    current = project.status
    if current == target:
        return
    if not can_transition(current, target):
        raise InvalidStateError(f"Cannot move project from {current.value} to {target.value}")
    project.status = target
    if target not in (S.FAILED, S.CANCELLED):
        project.error = None
    entry = {"from": current.value, "to": target.value, "at": datetime.now(UTC).isoformat()}
    if note:
        entry["note"] = note[:500]
    project.status_history = [*(project.status_history or []), entry]


def fail_project(project: VideoProject, error: str) -> None:
    step = project.status.value
    if project.status in TERMINAL and project.status != S.FAILED:
        return
    project.error = f"[{step}] {error}"[:4000]
    transition(project, S.FAILED, error)


def retry_target(project: VideoProject) -> S:
    """Choose the safest step to resume from after a failure."""
    history = project.status_history or []
    failed_at = next((h["from"] for h in reversed(history) if h["to"] in ("FAILED", "CANCELLED")), None)
    if failed_at == S.UPLOADING.value:
        return S.READY
    if failed_at in (S.PENDING.value, S.RESEARCHING.value, S.SCRIPTING.value) or project.script_id is None:
        return S.SCRIPTING
    return S.GENERATING_MEDIA
