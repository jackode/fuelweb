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

from flask import request, Response

from nailgun.database import db
from nailgun.api.models import Task
from nailgun.api.handlers.base import JSONHandler, content_json
from nailgun.api.handlers.base import SingleHandler, CollectionHandler


class TaskHandler(SingleHandler):
    fields = (
        "id",
        "cluster",
        "uuid",
        "name",
        "result",
        "message",
        "status",
        "progress"
    )
    model = Task

    def delete(self, task_id):
        task = self.get_object_or_404(Task, task_id)
        if task.status not in ("ready", "error"):
            self.abort(400, "You cannot delete running task manually")
        for subtask in task.subtasks:
            db.session.delete(subtask)
        db.session.delete(task)
        db.session.commit()
        resp = Response(status=204)
        del resp.headers['content-type']
        return resp


class TaskCollectionHandler(CollectionHandler):

    single = TaskHandler

    @content_json
    def get(self):
        cluster_id = request.args.get("cluster_id")
        if cluster_id:
            tasks = Task.query.filter_by(
                cluster_id=cluster_id).all()
        else:
            tasks = Task.query.all()
        return self.render(tasks)
