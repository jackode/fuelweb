# -*- coding: utf-8 -*-

from flask import Flask

from nailgun.settings import settings


def build_app():
    app = Flask(
        "nailgun",
        template_folder=settings.TEMPLATE_DIR,
        static_folder=settings.STATIC_DIR
    )
    return app


def load_urls(urls, app=None):
    if not app:
        app = application

    app.url_map.strict_slashes = False
    for url, handler in urls:
        if not str(handler.__name__) in app.view_functions:
            app.add_url_rule(
                url,
                view_func=handler.as_view(str(handler.__name__))
            )
    return app

application = build_app()
