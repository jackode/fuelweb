
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
import uuid
import string
import math
from datetime import datetime
from random import choice
from copy import deepcopy

import web
from netaddr import IPNetwork

from nailgun.logger import logger
from nailgun.volumes.manager import VolumeManager
from nailgun.api.fields import JSON
from nailgun.database import db
from nailgun.settings import settings


class Release(db.Model):
    __tablename__ = 'releases'
    __table_args__ = (
        db.UniqueConstraint('name', 'version'),
    )
    STATES = (
        'not_available',
        'downloading',
        'available'
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Unicode(100), nullable=False)
    version = db.Column(db.String(30), nullable=False)
    description = db.Column(db.Unicode)
    operating_system = db.Column(db.String(50), nullable=False)
    state = db.Column(db.Enum(*STATES, name='release_state'),
                      nullable=False,
                      default='not_available')
    networks_metadata = db.Column(JSON, default=[])
    attributes_metadata = db.Column(JSON, default={})
    volumes_metadata = db.Column(JSON, default={})
    clusters = db.relationship("Cluster", backref="release")


class ClusterChanges(db.Model):
    __tablename__ = 'cluster_changes'
    POSSIBLE_CHANGES = (
        'networks',
        'attributes',
        'disks'
    )
    id = db.Column(db.Integer, primary_key=True)
    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.id'))
    node_id = db.Column(
        db.Integer,
        db.ForeignKey('nodes.id', ondelete='CASCADE')
    )
    name = db.Column(
        db.Enum(*POSSIBLE_CHANGES, name='possible_changes'),
        nullable=False
    )


class Cluster(db.Model):
    __tablename__ = 'clusters'
    MODES = ('singlenode', 'multinode', 'ha')
    STATUSES = ('new', 'deployment', 'operational', 'error', 'remove')
    NET_MANAGERS = ('FlatDHCPManager', 'VlanManager')
    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(
        db.Enum(*MODES, name='cluster_mode'),
        nullable=False,
        default='multinode'
    )
    status = db.Column(
        db.Enum(*STATUSES, name='cluster_status'),
        nullable=False,
        default='new'
    )
    net_manager = db.Column(
        db.Enum(*NET_MANAGERS, name='cluster_net_manager'),
        nullable=False,
        default='FlatDHCPManager'
    )
    name = db.Column(db.Unicode(50), unique=True, nullable=False)
    release_id = db.Column(
        db.Integer,
        db.ForeignKey('releases.id'),
        nullable=False
    )
    nodes = db.relationship("Node", backref="cluster", cascade="delete")
    tasks = db.relationship("Task", backref="cluster", cascade="delete")
    attributes = db.relationship("Attributes", uselist=False,
                                 backref="cluster", cascade="delete")
    changes = db.relationship("ClusterChanges", backref="cluster",
                              cascade="delete")
    # We must keep all notifications even if cluster is removed.
    # It is because we want user to be able to see
    # the notification history so that is why we don't use
    # cascade="delete" in this relationship
    # During cluster deletion sqlalchemy engine will set null
    # into cluster foreign key column of notification entity
    notifications = db.relationship("Notification", backref="cluster")
    network_groups = db.relationship("NetworkGroup", backref="cluster",
                                     cascade="delete")

    @property
    def full_name(self):
        return '%s (id=%s, mode=%s)' % (self.name, self.id, self.mode)

    @classmethod
    def validate(cls, data):
        d = cls.validate_json(data)
        if d.get("name"):
            if Cluster.query.filter_by(
                name=d["name"]
            ).first():
                pass
                # c = web.webapi.conflict
                # c.message = "Environment with this name already exists"
                # raise c()
        if d.get("release"):
            release = Release.query.get(d.get("release"))
            if not release:
                pass
                # raise web.webapi.badrequest(message="Invalid release id")
        return d

    def add_pending_changes(self, changes_type, node_id=None):
        ex_chs = ClusterChanges.query.filter_by(
            cluster=self,
            name=changes_type
        )
        if not node_id:
            ex_chs = ex_chs.first()
        else:
            ex_chs = ex_chs.filter_by(node_id=node_id).first()
        # do nothing if changes with the same name already pending
        if ex_chs:
            return
        ch = ClusterChanges(
            cluster_id=self.id,
            name=changes_type
        )
        if node_id:
            ch.node_id = node_id
        db.session.add(ch)
        db.session.commit()

    def clear_pending_changes(self, node_id=None):
        chs = db.session.query(ClusterChanges).filter_by(
            cluster_id=self.id
        )
        if node_id:
            chs = chs.filter_by(node_id=node_id)
        map(db.session.delete, chs.all())
        db.session.commit()


class Node(db.Model):
    __tablename__ = 'nodes'
    NODE_STATUSES = (
        'ready',
        'discover',
        'provisioning',
        'provisioned',
        'deploying',
        'error'
    )
    NODE_ROLES = (
        'controller',
        'compute',
        'cinder',
    )
    NODE_ERRORS = (
        'deploy',
        'provision',
        'deletion'
    )
    id = db.Column(db.Integer, primary_key=True)
    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.id'))
    name = db.Column(db.Unicode(100))
    status = db.Column(
        db.Enum(*NODE_STATUSES, name='node_status'),
        nullable=False,
        default='discover'
    )
    meta = db.Column(JSON, default={})
    mac = db.Column(db.String(17), nullable=False, unique=True)
    ip = db.Column(db.String(15))
    fqdn = db.Column(db.String(255))
    manufacturer = db.Column(db.Unicode(50))
    platform_name = db.Column(db.String(150))
    progress = db.Column(db.Integer, default=0)
    os_platform = db.Column(db.String(150))
    role = db.Column(db.Enum(*NODE_ROLES, name='node_role'))
    pending_addition = db.Column(db.Boolean, default=False)
    pending_deletion = db.Column(db.Boolean, default=False)
    changes = db.relationship("ClusterChanges", backref="node")
    error_type = db.Column(db.Enum(*NODE_ERRORS, name='node_error_type'))
    error_msg = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, nullable=False)
    online = db.Column(db.Boolean, default=True)
    attributes = db.relationship("NodeAttributes",
                                 backref=db.backref("node"),
                                 uselist=False)
    interfaces = db.relationship("NodeNICInterface", backref="node",
                                 cascade="delete")

    @property
    def network_data(self):
        # It is required for integration tests; to get info about nets
        #   which must be created on target node
        from nailgun.network.manager import NetworkManager
        netmanager = NetworkManager()
        return netmanager.get_node_networks(self.id)

    @property
    def volume_manager(self):
        return VolumeManager(self)

    @property
    def needs_reprovision(self):
        return self.status == 'error' and self.error_type == 'provision'

    @property
    def needs_redeploy(self):
        changes = []
        if self.cluster is not None:
            def check_change(change):
                return change.name != 'disks' or change.node_id == self.id
            changes = filter(check_change, self.cluster.changes)
        cases = [
            self.status == 'error' and self.error_type == 'deploy',
            changes != []
        ]
        and_cases = [
            not self.pending_deletion
        ]
        return any(cases) and all(and_cases)

    @property
    def needs_redeletion(self):
        return self.status == 'error' and self.error_type == 'deletion'

    @property
    def human_readable_name(self):
        return self.name or self.mac

    def _check_interface_has_required_params(self, iface):
        return bool(iface.get('name') and iface.get('mac'))

    def _clean_iface(self, iface):
        # cleaning up unnecessary fields - set to None if bad
        for param in ["max_speed", "current_speed"]:
            val = iface.get(param)
            if not (isinstance(val, int) and val >= 0):
                val = None
            iface[param] = val
        return iface

    def update_meta(self, data):
        # helper for basic checking meta before updation
        result = []
        for iface in data["interfaces"]:
            if not self._check_interface_has_required_params(iface):
                logger.warning(
                    "Invalid interface data: {0}. "
                    "Interfaces are not updated.".format(iface)
                )
                data["interfaces"] = self.meta.get("interfaces")
                self.meta = data
                return
            result.append(self._clean_iface(iface))

        data["interfaces"] = result
        self.meta = data

    def create_meta(self, data):
        # helper for basic checking meta before creation
        result = []
        for iface in data["interfaces"]:
            if not self._check_interface_has_required_params(iface):
                logger.warning(
                    "Invalid interface data: {0}. "
                    "Skipping interface.".format(iface)
                )
                continue
            result.append(self._clean_iface(iface))

        data["interfaces"] = result
        self.meta = data


class NodeAttributes(db.Model):
    __tablename__ = 'node_attributes'
    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey('nodes.id'))
    volumes = db.Column(JSON, default=[])
    interfaces = db.Column(JSON, default={})


class IPAddr(db.Model):
    __tablename__ = 'ip_addrs'
    id = db.Column(db.Integer, primary_key=True)
    network = db.Column(
        db.Integer,
        db.ForeignKey('networks.id', ondelete="CASCADE")
    )
    node = db.Column(db.Integer, db.ForeignKey('nodes.id', ondelete="CASCADE"))
    ip_addr = db.Column(db.String(25), nullable=False)


class IPAddrRange(db.Model):
    __tablename__ = 'ip_addr_ranges'
    id = db.Column(db.Integer, primary_key=True)
    network_group_id = db.Column(
        db.Integer,
        db.ForeignKey('network_groups.id')
    )
    first = db.Column(db.String(25), nullable=False)
    last = db.Column(db.String(25), nullable=False)


class Vlan(db.Model):
    __tablename__ = 'vlan'
    id = db.Column(db.Integer, primary_key=True)
    network = db.relationship("Network",
                              backref=db.backref("vlan"))


class Network(db.Model):
    __tablename__ = 'networks'
    id = db.Column(db.Integer, primary_key=True)
    # can be nullable only for fuelweb admin net
    release = db.Column(db.Integer, db.ForeignKey('releases.id'))
    name = db.Column(db.Unicode(100), nullable=False)
    access = db.Column(db.String(20), nullable=False)
    vlan_id = db.Column(db.Integer, db.ForeignKey('vlan.id'))
    network_group_id = db.Column(
        db.Integer,
        db.ForeignKey('network_groups.id')
    )
    cidr = db.Column(db.String(25), nullable=False)
    gateway = db.Column(db.String(25))
    nodes = db.relationship(
        "Node",
        secondary=IPAddr.__table__,
        backref="networks")


class NetworkGroup(db.Model):
    __tablename__ = 'network_groups'
    NAMES = (
        # Node networks
        'fuelweb_admin',
        'storage',
        # internal in terms of fuel
        'management',
        'public',

        # VM networks
        'floating',
        # private in terms of fuel
        'fixed'
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(
        db.Enum(*NAMES, name='network_group_name'),
        nullable=False
    )
    access = db.Column(db.String(20), nullable=False)
    # can be nullable only for fuelweb admin net
    release = db.Column(db.Integer, db.ForeignKey('releases.id'))
    # can be nullable only for fuelweb admin net
    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.id'))
    network_size = db.Column(db.Integer, default=256)
    amount = db.Column(db.Integer, default=1)
    vlan_start = db.Column(db.Integer, default=1)
    networks = db.relationship("Network", cascade="delete",
                               backref="network_group")
    cidr = db.Column(db.String(25))
    gateway = db.Column(db.String(25))

    netmask = db.Column(db.String(25), nullable=False)
    ip_ranges = db.relationship(
        "IPAddrRange",
        backref="network_group"
    )

    @classmethod
    def generate_vlan_ids_list(cls, ng):
        if ng["vlan_start"] is None:
            return []
        vlans = [
            i for i in xrange(
                int(ng["vlan_start"]),
                int(ng["vlan_start"]) + int(ng["amount"])
            )
        ]
        return vlans


class NetworkConfiguration(object):
    @classmethod
    def update(cls, cluster, network_configuration):
        from nailgun.network.manager import NetworkManager
        network_manager = NetworkManager()
        if 'net_manager' in network_configuration:
            setattr(
                cluster,
                'net_manager',
                network_configuration['net_manager'])

        if 'networks' in network_configuration:
            for ng in network_configuration['networks']:
                ng_db = NetworkGroup.query.get(ng['id'])

                for key, value in ng.iteritems():
                    if key == "ip_ranges":
                        cls.__set_ip_ranges(ng['id'], value)
                    else:
                        if key == 'cidr' and \
                                not ng['name'] in ('public', 'floating'):
                            network_manager.update_ranges_from_cidr(
                                ng_db, value)

                        setattr(ng_db, key, value)

                network_manager.create_networks(ng_db)
                ng_db.cluster.add_pending_changes('networks')

    @classmethod
    def __set_ip_ranges(cls, network_group_id, ip_ranges):
        # deleting old ip ranges
        IPAddrRange.query.filter_by(
            network_group_id=network_group_id).delete()

        for r in ip_ranges:
            new_ip_range = IPAddrRange(
                first=r[0],
                last=r[1],
                network_group_id=network_group_id)
            db.session.add(new_ip_range)
        db.session.commit()


class AttributesGenerators(object):
    @classmethod
    def password(cls, arg=None):
        try:
            length = int(arg)
        except:
            length = 8
        chars = string.letters + string.digits
        return u''.join([choice(chars) for _ in xrange(length)])

    @classmethod
    def ip(cls, arg=None):
        if str(arg) in ("admin", "master"):
            return settings.MASTER_IP
        return "127.0.0.1"

    @classmethod
    def identical(cls, arg=None):
        return str(arg)


class Attributes(db.Model):
    __tablename__ = 'attributes'
    id = db.Column(db.Integer, primary_key=True)
    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.id'))
    editable = db.Column(JSON)
    generated = db.Column(JSON)

    def generate_fields(self):
        self.generated = self.traverse(self.generated)
        db.session.add(self)
        db.session.commit()

    @classmethod
    def traverse(cls, cdict):
        new_dict = {}
        if cdict:
            for i, val in cdict.iteritems():
                if isinstance(val, dict) and "generator" in val:
                    try:
                        generator = getattr(
                            AttributesGenerators,
                            val["generator"]
                        )
                    except AttributeError:
                        logger.error("Attribute error: %s" % val["generator"])
                        raise
                    else:
                        new_dict[i] = generator(val.get("generator_arg"))
                else:
                    new_dict[i] = cls.traverse(val)
        return new_dict

    def merged_attrs(self):
        return self._dict_merge(self.generated, self.editable)

    def merged_attrs_values(self):
        attrs = self.merged_attrs()
        for group_attrs in attrs.itervalues():
            for attr, value in group_attrs.iteritems():
                if isinstance(value, dict) and 'value' in value:
                    group_attrs[attr] = value['value']
        if 'common' in attrs:
            attrs.update(attrs.pop('common'))
        return attrs

    def _dict_merge(self, a, b):
        '''recursively merges dict's. not just simple a['key'] = b['key'], if
        both a and bhave a key who's value is a dict then dict_merge is called
        on both values and the result stored in the returned dictionary.'''
        if not isinstance(b, dict):
            return b
        result = deepcopy(a)
        for k, v in b.iteritems():
            if k in result and isinstance(result[k], dict):
                    result[k] = self._dict_merge(result[k], v)
            else:
                result[k] = deepcopy(v)
        return result


class Task(db.Model):
    __tablename__ = 'tasks'
    TASK_STATUSES = (
        'ready',
        'running',
        'error'
    )
    TASK_NAMES = (
        'super',

        # cluster
        'deploy',
        'deployment',
        'provision',
        'node_deletion',
        'cluster_deletion',
        'check_before_deployment',

        # network
        'check_networks',
        'verify_networks',

        # plugin
        'install_plugin',
        'update_plugin',
        'delete_plugin',

        # releases
        'download_release'
    )
    id = db.Column(db.Integer, primary_key=True)
    cluster_id = db.Column(db.Integer, db.ForeignKey('clusters.id'))
    uuid = db.Column(db.String(36), nullable=False,
                     default=lambda: str(uuid.uuid4()))
    name = db.Column(
        db.Enum(*TASK_NAMES, name='task_name'),
        nullable=False,
        default='super'
    )
    message = db.Column(db.Text)
    status = db.Column(
        db.Enum(*TASK_STATUSES, name='task_status'),
        nullable=False,
        default='running'
    )
    progress = db.Column(db.Integer, default=0)
    cache = db.Column(JSON, default={})
    result = db.Column(JSON, default={})
    parent_id = db.Column(db.Integer, db.ForeignKey('tasks.id'))
    subtasks = db.relationship(
        "Task",
        backref=db.backref('parent', remote_side=[id])
    )
    notifications = db.relationship(
        "Notification",
        backref=db.backref('task', remote_side=[id])
    )
    # Task weight is used to calculate supertask progress
    # sum([t.progress * t.weight for t in supertask.subtasks]) /
    # sum([t.weight for t in supertask.subtasks])
    weight = db.Column(db.Float, default=1.0)

    def __repr__(self):
        return "<Task '{0}' {1} ({2}) {3}>".format(
            self.name,
            self.uuid,
            self.cluster_id,
            self.status
        )

    def create_subtask(self, name):
        if not name:
            raise ValueError("Subtask name not specified")

        task = Task(name=name, cluster=self.cluster)

        self.subtasks.append(task)
        db.session.commit()
        return task


class Notification(db.Model):
    __tablename__ = 'notifications'

    NOTIFICATION_STATUSES = (
        'read',
        'unread',
    )

    NOTIFICATION_TOPICS = (
        'discover',
        'done',
        'error',
    )

    id = db.Column(db.Integer, primary_key=True)
    cluster_id = db.Column(
        db.Integer,
        db.ForeignKey('clusters.id', ondelete='SET NULL')
    )
    node_id = db.Column(
        db.Integer,
        db.ForeignKey('nodes.id', ondelete='SET NULL')
    )
    task_id = db.Column(
        db.Integer,
        db.ForeignKey('tasks.id', ondelete='SET NULL')
    )
    topic = db.Column(
        db.Enum(*NOTIFICATION_TOPICS, name='notif_topic'),
        nullable=False
    )
    message = db.Column(db.Text)
    status = db.Column(
        db.Enum(*NOTIFICATION_STATUSES, name='notif_status'),
        nullable=False,
        default='unread'
    )
    datetime = db.Column(db.DateTime, nullable=False)


class L2Topology(db.Model):
    __tablename__ = 'l2_topologies'
    id = db.Column(db.Integer, primary_key=True)
    network_id = db.Column(
        db.Integer,
        db.ForeignKey('network_groups.id', ondelete="CASCADE"),
        nullable=False
    )


class L2Connection(db.Model):
    __tablename__ = 'l2_connections'
    id = db.Column(db.Integer, primary_key=True)
    topology_id = db.Column(
        db.Integer,
        db.ForeignKey('l2_topologies.id', ondelete="CASCADE"),
        nullable=False
    )
    interface_id = db.Column(
        db.Integer,
        # If interface is removed we should somehow remove
        # all L2Topologes which include this interface.
        db.ForeignKey('node_nic_interfaces.id', ondelete="CASCADE"),
        nullable=False
    )


class AllowedNetworks(db.Model):
    __tablename__ = 'allowed_networks'
    id = db.Column(db.Integer, primary_key=True)
    network_id = db.Column(
        db.Integer,
        db.ForeignKey('network_groups.id', ondelete="CASCADE"),
        nullable=False
    )
    interface_id = db.Column(
        db.Integer,
        db.ForeignKey('node_nic_interfaces.id', ondelete="CASCADE"),
        nullable=False
    )


class NetworkAssignment(db.Model):
    __tablename__ = 'net_assignments'
    id = db.Column(db.Integer, primary_key=True)
    network_id = db.Column(
        db.Integer,
        db.ForeignKey('network_groups.id', ondelete="CASCADE"),
        nullable=False
    )
    interface_id = db.Column(
        db.Integer,
        db.ForeignKey('node_nic_interfaces.id', ondelete="CASCADE"),
        nullable=False
    )


class NodeNICInterface(db.Model):
    __tablename__ = 'node_nic_interfaces'
    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(
        db.Integer,
        db.ForeignKey('nodes.id', ondelete="CASCADE"),
        nullable=False
    )
    name = db.Column(db.String(128), nullable=False)
    mac = db.Column(db.String(32), nullable=False)
    max_speed = db.Column(db.Integer)
    current_speed = db.Column(db.Integer)
    allowed_networks = db.relationship(
        "NetworkGroup",
        secondary=AllowedNetworks.__table__,
    )
    assigned_networks = db.relationship(
        "NetworkGroup",
        secondary=NetworkAssignment.__table__,
    )


class Plugin(db.Model):
    __tablename__ = 'plugins'
    TYPES = ('nailgun', 'fuel')

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.Enum(*TYPES, name='plugin_type'), nullable=False)
    name = db.Column(db.String(128), nullable=False, unique=True)
    state = db.Column(db.String(128), nullable=False, default='registered')
    version = db.Column(db.String(128), nullable=False)


class RedHatAccount(db.Model):
    __tablename__ = 'red_hat_accounts'
    LICENSE_TYPES = ('rhsm', 'rhn')

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(100), nullable=False)
    license_type = db.Column(db.Enum(*LICENSE_TYPES, name='license_type'),
                             nullable=False)
    satellite = db.Column(db.String(250))
    activation_key = db.Column(db.String(300))
