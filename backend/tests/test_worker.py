from datetime import datetime, timedelta, timezone

from app.worker import _minutes_since, _order_ids


def test_never_run_is_due():
    # 7 jours = 10080 min : un défaut trop bas empêchait le premier calcul des profils.
    assert _minutes_since({}, "outlet_profiles") >= 10080
    assert _minutes_since({"rss": datetime.now(timezone.utc)}, "outlet_profiles") >= 10080


def test_recent_run_not_due():
    last = {"outlet_profiles": datetime.now(timezone.utc) - timedelta(hours=2)}
    assert _minutes_since(last, "outlet_profiles") < 1440


def test_never_collected_go_first_then_the_cursor_rotates():
    # Après le 3 : 4, 5, 6, 1, 2, 3. Jamais lus : 5, 6, 2. Déjà dus : 4, 1.
    assert _order_ids([1, 2, 3, 4, 5, 6], 3, {2, 5, 6}, {1, 4}) == [5, 6, 2, 4, 1]


def test_cursor_wraps_to_the_start():
    assert _order_ids([10, 20, 30], 30, set(), {10, 20, 30}) == [10, 20, 30]


def test_outlets_without_articles_come_before_the_others():
    assert _order_ids([1, 2], 0, {1, 2}, set(), {2}) == [2, 1]
