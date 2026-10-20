from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSettings


def get_app_settings(db: Session, owner_id: int) -> AppSettings:
    s = db.scalar(select(AppSettings).where(AppSettings.owner_id == owner_id))
    if s is None:
        s = AppSettings(owner_id=owner_id, llm_routing={}, llm_models={}, encrypted_api_keys={},
                        publish_days=[0, 1, 2, 3, 4, 5, 6])
        db.add(s)
        db.flush()
    return s
