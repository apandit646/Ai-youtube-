import logging

from sqlalchemy.orm import Session

from app.core.logging import redact
from app.models import AuditLog

log = logging.getLogger("audit")


def audit(db: Session, owner_id: int | None, action: str, entity_type: str = "", entity_id: object = "",
          **details: object) -> None:
    """Record an auditable action. Values are redacted defensively; never pass secrets here."""
    safe = {k: redact(str(v)) if isinstance(v, str) else v for k, v in details.items()}
    db.add(AuditLog(owner_id=owner_id, action=action, entity_type=entity_type, entity_id=str(entity_id), details=safe))
    log.info("%s %s:%s", action, entity_type, entity_id)
