"""Read-only list presentation; never dispatches a checker or a tool."""
from ...director.review.reports import status
from ...director.state.removal import revision, visible


def summary(db, row):
    return dict(check=status(db, row), removal_revision=revision(db, row['id']))


def active(db, row):
    return visible(db, row['id'])
