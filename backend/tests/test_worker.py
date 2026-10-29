from datetime import datetime, timedelta, timezone

from app.worker import _minutes_since


def test_never_run_is_due():
    # 7 jours = 10080 min : un défaut trop bas empêchait le premier calcul des profils.
    assert _minutes_since({}, "outlet_profiles") >= 10080
    assert _minutes_since({"rss": datetime.now(timezone.utc)}, "outlet_profiles") >= 10080


def test_recent_run_not_due():
    last = {"outlet_profiles": datetime.now(timezone.utc) - timedelta(hours=2)}
    assert _minutes_since(last, "outlet_profiles") < 1440
