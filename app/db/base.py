"""Single import point for the declarative Base.

Models import `Base` from here (not from `app.db.session`) so the ORM metadata is
defined in one place and swapping the engine/session setup never touches models.

Importing this module also imports every model module, because SQLAlchemy resolves
relationships by class name at first use: registering `User` without
`OAuthAccount` (or the reverse) is the "failed to locate a name" error. The import
is done through `importlib`, which is a no-op for a module that is already being
imported — so importing `app.models.user` directly still works and cannot deadlock
on a partial module.
"""

import importlib

from app.db.session import Base  # noqa: F401

_MODEL_MODULES = (
    "app.models.user",
    "app.models.oauth",
    "app.models.project",
    "app.models.analysis",
)

for _module in _MODEL_MODULES:
    importlib.import_module(_module)

del _module
