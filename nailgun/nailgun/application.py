# -*- coding: utf-8 -*-

#    Copyright 2013 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

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
