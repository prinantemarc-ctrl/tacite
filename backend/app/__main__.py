"""Entry point for `python -m app.seed`."""

from .seed import seed
from .database import init_db

init_db()
seed()
