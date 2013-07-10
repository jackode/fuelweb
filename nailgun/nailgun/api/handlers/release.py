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

from flask import request

from nailgun.errors import errors
from nailgun.api.models import Release
from nailgun.api.validators.release import ReleaseValidator
from nailgun.api.handlers.base import content_json
from nailgun.api.handlers.base import SingleHandler, CollectionHandler


class ReleaseHandler(SingleHandler):
    fields = (
        "id",
        "name",
        "version",
        "description",
        "operating_system",
        "state"
    )
    model = Release
    validator = ReleaseValidator

    @content_json
    def put(self, release_id):
        release = self.get_object_or_404(Release, release_id)

        data = self.checked_data()

        for key, value in data.iteritems():
            setattr(release, key, value)
        db.session.commit()
        return self.render(release)

    def delete(self, release_id):
        release = self.get_object_or_404(Release, release_id)
        db.session.delete(release)
        db.session.commit()
        self.abort(204)


class ReleaseCollectionHandler(CollectionHandler):

    validator = ReleaseValidator
    single = ReleaseHandler

    @content_json
    def post(self):
        data = self.checked_data()

        release = Release()
        for key, value in data.iteritems():
            setattr(release, key, value)
        db.session.add(release)
        db.session.commit()
        return self.render(release), 201
