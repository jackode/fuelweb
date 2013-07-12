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

import re
import os
import time
import json
import logging
import tarfile
import tempfile
from itertools import dropwhile

from flask import make_response, request

from nailgun.settings import settings
from nailgun.api.models import Node
from nailgun.api.handlers.base import JSONHandler, content_json

logger = logging.getLogger(__name__)


def read_backwards(file, bufsize=4096):
    buf = ""
    try:
        file.seek(-1, 1)
    except IOError:
        return
    trailing_newline = False
    if file.read(1) == "\n":
        trailing_newline = True
        file.seek(-1, 1)

    while True:
        newline_pos = buf.rfind("\n")
        pos = file.tell()
        if newline_pos != -1:
            line = buf[newline_pos + 1:]
            buf = buf[:newline_pos]
            if pos or newline_pos or trailing_newline:
                line += "\n"
            yield line
        elif pos:
            toread = min(bufsize, pos)
            file.seek(-toread, 1)
            buf = file.read(toread) + buf
            file.seek(-toread, 1)
            if pos == toread:
                buf = "\n" + buf
        else:
            return


class LogEntryCollectionHandler(JSONHandler):

    @content_json
    def get(self):
        user_data = request.args
        date_before = user_data.get('date_before')
        if date_before:
            try:
                date_before = time.strptime(date_before,
                                            settings.UI_LOG_DATE_FORMAT)
            except ValueError:
                logger.debug("Invalid 'date_before' value: %s", date_before)
                self.abort(400, "Invalid 'date_before' value")
        date_after = user_data.get('date_after')
        if date_after:
            try:
                date_after = time.strptime(date_after,
                                           settings.UI_LOG_DATE_FORMAT)
            except ValueError:
                logger.debug("Invalid 'date_after' value: %s", date_after)
                self.abort(400, "Invalid 'date_after' value")
        truncate_log = bool(user_data.get('truncate_log'))

        if not user_data.get('source'):
            logger.debug("'source' must be specified")
            self.abort(400, "'source' must be specified")

        log_config = filter(lambda lc: lc['id'] == user_data.get('source'),
                            settings.LOGS)
        # If log source not found or it is fake source but we are run without
        # fake tasks.
        if not log_config or (log_config[0].get('fake') and
                              not settings.FAKE_TASKS):
            logger.debug("Log source %r not found", user_data.source)
            self.abort(404, "Log source not found")
        log_config = log_config[0]

        # If it is 'remote' and not 'fake' log source then calculate log file
        # path by base dir, node IP and relative path to file.
        # Otherwise return absolute path.
        node = None
        if log_config['remote'] and not log_config.get('fake'):
            if not user_data.get('node'):
                self.abort(400, "'node' must be specified")
            node = Node.query.get(user_data.get("node"))
            if not node:
                self.abort(400, "Node not found")
            if not node.ip:
                logger.error('Node %r has no assigned ip', node.id)
                self.abort(500, "Node has no assigned ip")

            if node.status == "discover":
                ndir = node.ip
            else:
                ndir = node.fqdn

            remote_log_dir = os.path.join(log_config['base'], ndir)
            if not os.path.exists(remote_log_dir):
                logger.debug("Log files dir %r for node %s not found",
                             remote_log_dir, node.id)
                self.abort(404, "Log files dir for node not found")

            log_file = os.path.join(remote_log_dir, log_config['path'])
        else:
            log_file = log_config['path']

        if not os.path.exists(log_file):
            if node:
                logger.debug("Log file %r for node %s not found",
                             log_file, node.id)
            else:
                logger.debug("Log file %r not found", log_file)
            self.abort(404, "Log file not found")

        level = user_data.get('level')
        allowed_levels = log_config['levels']
        if level is not None:
            if not (level in log_config['levels']):
                self.abort(400, "Invalid level")
            allowed_levels = [l for l in dropwhile(lambda l: l != level,
                                                   log_config['levels'])]
        try:
            regexp = re.compile(log_config['regexp'])
        except re.error, e:
            logger.error('Invalid regular expression for file %r: %s',
                         log_config['id'], e)
            self.abort(500, "Invalid regular expression in config")

        entries = []
        to_byte = None
        try:
            to_byte = int(user_data.get('to', 0))
        except ValueError:
            logger.debug("Invalid 'to' value: %d", to_byte)
            self.abort(400, "Invalid 'to' value")

        log_file_size = os.stat(log_file).st_size
        if to_byte >= log_file_size:
            return json.dumps({
                'entries': [],
                'to': log_file_size,
                'has_more': False,
            })

        try:
            max_entries = int(user_data.get('max_entries',
                                            settings.TRUNCATE_LOG_ENTRIES))
        except ValueError:
            logger.debug("Invalid 'max_entries' value: %d", max_entries)
            self.abort(400, "Invalid 'max_entries' value")

        has_more = False
        with open(log_file, 'r') as f:
            f.seek(0, 2)
            # we need to calculate current position manually instead of using
            # tell() because read_backwards uses buffering
            pos = f.tell()
            multilinebuf = []
            for line in read_backwards(f):
                pos -= len(line)
                if not truncate_log and pos < to_byte:
                    has_more = pos > 0
                    break
                entry = line.rstrip('\n')
                if not len(entry):
                    continue
                if 'skip_regexp' in log_config and \
                        re.match(log_config['skip_regexp'], entry):
                        continue
                m = regexp.match(entry)
                if m is None:
                    if log_config.get('multiline'):
                        #  Add next multiline part to last entry if it exist.
                        multilinebuf.append(entry)
                    else:
                        logger.debug("Unable to parse log entry '%s' from %s",
                                     entry, log_file)
                    continue
                entry_text = m.group('text')
                if len(multilinebuf):
                    multilinebuf.reverse()
                    entry_text += '\n' + '\n'.join(multilinebuf)
                    multilinebuf = []
                entry_level = m.group('level').upper() or 'INFO'
                if level and not (entry_level in allowed_levels):
                    continue
                try:
                    entry_date = time.strptime(m.group('date'),
                                               log_config['date_format'])
                except ValueError:
                    logger.debug("Unable to parse date from log entry."
                                 " Date format: %r, date part of entry: %r",
                                 log_config['date_format'],
                                 m.group('date'))
                    continue
                entries.append([
                    time.strftime(settings.UI_LOG_DATE_FORMAT, entry_date),
                    entry_level,
                    entry_text
                ])
                if truncate_log and len(entries) >= max_entries:
                    has_more = True
                    break

        return {
            'entries': entries,
            'to': log_file_size,
            'has_more': has_more,
        }


class LogPackageHandler(JSONHandler):

    def get(self):
        f = tempfile.TemporaryFile(mode='r+b')
        tf = tarfile.open(fileobj=f, mode='w:gz')
        for arcname, path in settings.LOGS_TO_PACK_FOR_SUPPORT.items():
            tf.add(path, arcname)
        tf.close()

        filename = 'fuelweb-logs-%s.tar.gz' % (
            time.strftime('%Y-%m-%d_%H:%M:%S', time.localtime()))

        length = f.tell()
        f.seek(0)
        response = make_response(f.read())
        response.headers['Content-Type'] = 'application/octet-stream'
        response.headers['Content-Disposition'] = \
            'attachment; filename="%s"' % (filename)
        response.headers['Content-Length'] = length
        return response


class LogSourceCollectionHandler(JSONHandler):

    @content_json
    def get(self):
        return settings.LOGS


class LogSourceByNodeCollectionHandler(JSONHandler):

    @content_json
    def get(self, node_id):
        node = self.get_object_or_404(Node, node_id)

        def getpath(x):
            if x.get('fake'):
                if settings.FAKE_TASKS:
                    return x['path']
                else:
                    return ''
            else:
                if node.status == "discover":
                    ndir = node.ip
                else:
                    ndir = node.fqdn
                return os.path.join(x['base'], ndir, x['path'])

        f = lambda x: (
            x.get('remote') and x.get('path') and x.get('base') and
            os.access(getpath(x), os.R_OK) and os.path.isfile(getpath(x))
        )
        sources = filter(f, settings.LOGS)
        return sources
