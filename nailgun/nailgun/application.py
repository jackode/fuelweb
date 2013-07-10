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

application = build_app()
