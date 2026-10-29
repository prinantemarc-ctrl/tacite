"""Request-scoped UI locale. Chrome and mapped labels follow Accept-Language."""

from __future__ import annotations

from contextvars import ContextVar

_locale: ContextVar[str] = ContextVar("ui_locale", default="fr")


def parse_accept_language(header: str | None) -> str:
    raw = (header or "fr").lower()
    for part in raw.split(","):
        tag = part.split(";")[0].strip()
        if tag.startswith("en"):
            return "en"
        if tag.startswith("fr"):
            return "fr"
    return "fr"


def set_locale(lang: str) -> None:
    _locale.set("en" if lang == "en" else "fr")


def get_locale() -> str:
    return _locale.get()


def axis_labels() -> dict[str, str]:
    from .kits import axis_labels_for, AXIS_CATALOG
    loc = get_locale()
    base = axis_labels_for(loc)
    # kits custom ajoutés après import
    extra = {}
    for i, a in AXIS_CATALOG.items():
        if i not in base:
            extra[i] = a.get("label_en" if loc == "en" else "label_fr") or i
    return {**base, **extra}


def axis_poles_map() -> dict[str, tuple[str, str]]:
    from .kits import axis_poles_for, AXIS_CATALOG
    loc = get_locale()
    base = axis_poles_for(loc)
    extra = {}
    for i, a in AXIS_CATALOG.items():
        if i not in base:
            extra[i] = (a.get("neg_en" if loc == "en" else "neg_fr") or "−", a.get("pos_en" if loc == "en" else "pos_fr") or "+")
    return {**base, **extra}


def axis_label(axis: str) -> str:
    return axis_labels().get(axis, axis)


def axis_poles(axis: str) -> tuple[str, str]:
    return axis_poles_map().get(axis, ("−", "+"))


def msg(fr: str, en: str) -> str:
    return en if get_locale() == "en" else fr
