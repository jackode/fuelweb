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

import json
import uuid
from wsgiref.handlers import format_date_time
from datetime import datetime
from functools import wraps

from werkzeug.exceptions import HTTPException
from flask import make_response
from flask import abort
from flask import request, Response
from flask.views import MethodView, MethodViewType

from nailgun.errors import errors
from nailgun.logger import logger
from nailgun.api.validators.base import BasicValidator


def add_response_headers(headers={}):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            resp = make_response(f(*args, **kwargs))
            h = resp.headers
            for header, value in headers.items():
                h[header] = value
            return resp
        return decorated_function
    return decorator


def build_json_response(data):
    if type(data) in (dict, list):
        return json.dumps(data, indent=4)
    return data


def content_json(f):
    @wraps(f)
    @add_response_headers({
        'Content-Type': 'application/json',
        'Cache-Control': 'store, no-cache, must-revalidate,'
                         ' post-check=0, pre-check=0',
        'Pragma': 'no-cache',
        'Expires': datetime.fromtimestamp(0).strftime(
            '%a, %d %b %Y %H:%M:%S GMT'
        )
    })
    def decorated_function(*args, **kwargs):
        res = f(*args, **kwargs)
        if isinstance(res, tuple):
            return Response(build_json_response(res[0]), status=res[1])
        else:
            return Response(build_json_response(res), status=200)
    return decorated_function


class JSONHTTPException(HTTPException):
    def __init__(self, description=None, response=None, code=400):
        super(JSONHTTPException, self).__init__(description, response)
        self.code = code

    def get_body(self, environ):
        return json.dumps({
            "error": self.get_description(environ)
        })

    def get_headers(self, environ):
        return [('Content-Type', 'application/json')]


handlers = {}


class HandlerRegistrator(MethodViewType):
    def __init__(cls, name, bases, dct):
        super(HandlerRegistrator, cls).__init__(name, bases, dct)
        if hasattr(cls, 'model') and cls.model:
            key = cls.model.__name__
            if key in handlers:
                logger.warning("Handler for %s already registered" % key)
                return
            handlers[key] = cls


class JSONHandler(MethodView):
    __metaclass__ = HandlerRegistrator
    validator = BasicValidator

    fields = []

    def abort(self, status_code, body=None, headers={}):
        raise JSONHTTPException(
            body,
            Response(body, status=status_code),
            status_code
        )

    def get_object_or_404(self, model, *args, **kwargs):
        # should be in ('warning', 'Log message') format
        # (loglevel, message)
        log_404 = kwargs.pop("log_404") if "log_404" in kwargs else None
        log_get = kwargs.pop("log_get") if "log_get" in kwargs else None
        if "id" in kwargs:
            obj = model.query.get(kwargs["id"])
        elif len(args) > 0:
            obj = model.query.get(args[0])
        else:
            obj = model.query.filter(**kwargs).all()
        if not obj:
            if log_404:
                getattr(logger, log_404[0])(log_404[1])
            abort(404)
        else:
            if log_get:
                getattr(logger, log_get[0])(log_get[1])
        return obj

    def checked_data(self, validate_method=None):
        try:
            if validate_method:
                data = validate_method(request.data)
            else:
                data = self.validator.validate(request.data)
        except (
            errors.InvalidInterfacesInfo,
            errors.InvalidMetadata
        ) as exc:
            notifier.notify("error", str(exc))
            self.abort(400, str(exc))
        except (
            errors.AlreadyExists
        ) as exc:
            self.abort(409, str(exc))
        except (
            errors.InvalidData,
            Exception
        ) as exc:
            self.abort(400, str(exc))
        return data

    @classmethod
    def render_one(cls, instance, fields=None):
        return cls.render(cls, instance, fields=None)

    @classmethod
    def render(cls, instance, fields=None):
        json_data = {}
        use_fields = fields if fields else cls.fields
        if not use_fields:
            raise ValueError("No fields for serialize")
        for field in use_fields:
            if isinstance(field, (tuple,)):
                if field[1] == '*':
                    subfields = None
                else:
                    subfields = field[1:]

                value = getattr(instance, field[0])
                rel = getattr(
                    instance.__class__, field[0]).impl.__class__.__name__
                if value is None:
                    pass
                elif rel == 'ScalarObjectAttributeImpl':
                    handler = handlers[value.__class__.__name__]
                    json_data[field[0]] = handler.render(
                        value, fields=subfields
                    )
                elif rel == 'CollectionAttributeImpl':
                    if not value:
                        json_data[field[0]] = []
                    else:
                        handler = handlers[value[0].__class__.__name__]
                        json_data[field[0]] = [
                            handler.render(v, fields=subfields) for v in value
                        ]
            else:
                value = getattr(instance, field)
                if value is None:
                    json_data[field] = value
                else:
                    f = getattr(instance.__class__, field)
                    if hasattr(f, "impl"):
                        rel = f.impl.__class__.__name__
                        if rel == 'ScalarObjectAttributeImpl':
                            json_data[field] = value.id
                        elif rel == 'CollectionAttributeImpl':
                            json_data[field] = [v.id for v in value]
                        else:
                            json_data[field] = value
                    else:
                        json_data[field] = value
        return json_data


class SingleHandler(JSONHandler):

    model = None
    fields = ("id",)

    @content_json
    def get(self, *args):
        return self.render(
            self.get_object_or_404(self.model, args[0])
        )


class CollectionHandler(JSONHandler):

    single = None
    fields = ()

    @content_json
    def get(self):
        return self.render(
            self.single.model.query.all()
        )

    @classmethod
    def render_one(cls, instance, fields=None):
        return JSONHandler.render(
            instance,
            fields or cls.fields or cls.single.fields
        )

    def render(self, items):
        return map(self.render_one, items)
