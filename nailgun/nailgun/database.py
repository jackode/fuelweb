# -*- coding: utf-8 -*-

import traceback

from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.exc import ProgrammingError
from sqlalchemy import create_engine
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.sqlalchemy import BaseQuery

from nailgun.logger import logger
from nailgun.settings import settings
from nailgun.application import application


if settings.DATABASE['engine'] == 'sqlite':
    db_str = "{engine}://{path}".format(
        engine='sqlite',
        path="/" + settings.DATABASE['name']
    )
else:
    db_str = "{engine}://{user}:{passwd}@{host}:{port}/{name}".format(
        **settings.DATABASE
    )

engine = create_engine(db_str, client_encoding='utf8')

application.config['SQLALCHEMY_DATABASE_URI'] = db_str
db = SQLAlchemy(application)


class NoCacheQuery(BaseQuery):
    """
    Override for common Query class.
    Needed for automatic refreshing objects
    from database during every query for evading
    problems with multiple sessions
    """
    def __init__(self, *args, **kwargs):
        self._populate_existing = True
        super(NoCacheQuery, self).__init__(*args, **kwargs)


def syncdb():
    import nailgun.api.models
    db.create_all()


def dropdb():
    tables = [name for (name,) in db.session.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
    for table in tables:
        db.session.execute("DROP TABLE IF EXISTS %s CASCADE" % table)

    # sql query to list all types, equivalent to psql's \dT+
    types = [name for (name,) in db.session.execute("""
        SELECT t.typname as type FROM pg_type t
        LEFT JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
        WHERE (t.typrelid = 0 OR (
            SELECT c.relkind = 'c' FROM pg_catalog.pg_class c
            WHERE c.oid = t.typrelid
        ))
        AND NOT EXISTS(
            SELECT 1 FROM pg_catalog.pg_type el
            WHERE el.oid = t.typelem AND el.typarray = t.oid
        )
        AND n.nspname = 'public'
        """)]
    for type_ in types:
        db.session.execute("DROP TYPE IF EXISTS %s CASCADE" % type_)
    db.session.commit()


def make_session():
    return scoped_session(
        sessionmaker(bind=engine, query_cls=NoCacheQuery)
    )()


def flush():
    import nailgun.api.models as models
    import sqlalchemy.ext.declarative as dec
    session = db.session
    for attr in dir(models):
        attr_impl = getattr(models, attr)
        if isinstance(attr_impl, dec.DeclarativeMeta) \
                and not attr_impl is models.db:
            map(session.delete, session.query(attr_impl).all())
    # for table in reversed(models.Base.metadata.sorted_tables):
    #     session.execute(table.delete())
    session.commit()
