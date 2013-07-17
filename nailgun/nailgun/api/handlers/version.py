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
import json

from flask.views import MethodView

from nailgun.settings import settings
from nailgun.api.handlers.base import JSONHandler, content_json


class VersionHandler(MethodView):

    @content_json
    def get(self):
        return {
            "sha": str(settings.COMMIT_SHA),
            "release": str(settings.PRODUCT_VERSION),
            "fuel_sha": str(settings.FUEL_COMMIT_SHA)
        }
