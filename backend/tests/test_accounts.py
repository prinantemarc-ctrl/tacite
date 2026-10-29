"""Comptes : mot de passe, nom, et présence de user_id sur chaque table métier."""

import pytest

from app.accounts import hash_password, normalize_username, verify_password
from app.models import TENANT_MODELS, Setting


def test_password_roundtrip():
    stored = hash_password("correct-horse")
    assert stored.startswith("scrypt$")
    assert verify_password("correct-horse", stored)
    assert not verify_password("wrong-horse", stored)
    assert not verify_password("correct-horse", "nope")


def test_username_normalized():
    assert normalize_username("  Ada   Lovelace ") == "ada lovelace"


@pytest.mark.parametrize("raw", ["", "a", "ab", "x" * 41, "bad/name"])
def test_username_rejected(raw):
    with pytest.raises(ValueError):
        normalize_username(raw)


def test_every_business_table_has_an_owner():
    for cls in TENANT_MODELS:
        assert "user_id" in cls.__table__.c, cls.__tablename__
    assert list(Setting.__table__.primary_key.columns.keys()) == ["user_id", "key"]
