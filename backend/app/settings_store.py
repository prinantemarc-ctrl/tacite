"""Settings stored in the database, merged over code defaults. One row set per account."""

from sqlalchemy.orm import Session

from .constants import DEFAULT_SETTINGS
from .models import Setting
from .tenant import current_user_id


def get_settings(db: Session) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    uid = current_user_id()
    if uid is None:
        return merged
    for row in db.query(Setting).filter(Setting.user_id == uid).all():
        merged[row.key] = row.value
    return merged


def get_setting(db: Session, key: str):
    uid = current_user_id()
    if uid is None:
        return DEFAULT_SETTINGS.get(key)
    row = db.get(Setting, (uid, key))
    if row is not None:
        return row.value
    return DEFAULT_SETTINGS.get(key)


def set_setting(db: Session, key: str, value) -> None:
    uid = current_user_id()
    if uid is None:
        raise RuntimeError("réglage hors compte")
    row = db.get(Setting, (uid, key))
    if row is None:
        db.add(Setting(user_id=uid, key=key, value=value))
    else:
        row.value = value
    db.commit()
