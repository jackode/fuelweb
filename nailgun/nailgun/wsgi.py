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

import os
import sys
from signal import signal, SIGTERM

from flask.ext.sqlalchemy import SQLAlchemy

curdir = os.path.dirname(__file__)
sys.path.insert(0, curdir)

from nailgun.settings import settings

from nailgun.urls import urls
from nailgun.application import application, load_urls
from nailgun.logger import logger, HTTPLoggerMiddleware


# TODO: logging middleware
def build_middleware(app):
    middleware_list = [
        HTTPLoggerMiddleware
    ]

    logger.debug('Initialize middleware: %s' %
                 (map(lambda x: x.__name__, middleware_list)))

    return app(*middleware_list)


def run_server(debug=False, **kwargs):
    load_urls(urls)
    application.run(
        debug=debug,
        host=kwargs.get("host") or settings.LISTEN_ADDRESS,
        port=kwargs.get("port") or int(settings.LISTEN_PORT)
    )


def appstart(keepalive=False):
    logger.info("Fuel-Web {0} SHA: {1}\nFuel SHA: {2}".format(
        settings.PRODUCT_VERSION,
        settings.COMMIT_SHA,
        settings.FUEL_COMMIT_SHA
    ))

    from nailgun.rpc import threaded
    from nailgun.keepalive import keep_alive

    if keepalive:
        logger.info("Running KeepAlive watcher...")
        keep_alive.start()

    if not settings.FAKE_TASKS:
        if not keep_alive.is_alive() \
                and not settings.FAKE_TASKS_AMQP:
            logger.info("Running KeepAlive watcher...")
            keep_alive.start()
        rpc_process = threaded.RPCKombuThread()
        logger.info("Running RPC consumer...")
        rpc_process.start()
    logger.info("Running WSGI app...")

    #wsgifunc = build_middleware(app.wsgifunc)

    run_server(
        host=settings.LISTEN_ADDRESS,
        port=int(settings.LISTEN_PORT),
        debug=True
    )

    logger.info("Stopping WSGI app...")
    if keep_alive.is_alive():
        logger.info("Stopping KeepAlive watcher...")
        keep_alive.join()
    if not settings.FAKE_TASKS:
        logger.info("Stopping RPC consumer...")
        rpc_process.join()
    logger.info("Done")
