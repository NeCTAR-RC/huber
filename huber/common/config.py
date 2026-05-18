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

import copy
import operator
import socket
import sys

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging


LOG = logging.getLogger(__name__)


default_opts = [
    cfg.StrOpt(
        "host",
        default=socket.gethostname(),
        help=(
            "Name of this huber instance. Used as the oslo.messaging "
            "server identity and in log records. Defaults to the system "
            "hostname."
        ),
    ),
]

worker_opts = [
    cfg.IntOpt(
        "workers",
        default=1,
        help=(
            "Number of cotyledon worker processes to run for the "
            "notification consumer. Each worker opens its own listener; "
            "with a shared pool name they load-balance messages between "
            "them."
        ),
    ),
]

notification_opts = [
    cfg.StrOpt(
        "exchange",
        default="ceilometer",
        help=(
            "Message bus exchange to listen on. Huber expects ceilometer "
            "to forward selected events here via its event_pipeline."
        ),
    ),
    cfg.StrOpt(
        "topic",
        default="huber",
        help=(
            "Topic to listen on. Configure ceilometer's event_pipeline "
            "sink to publish to this topic."
        ),
    ),
    cfg.StrOpt(
        "pool",
        default="huber",
        help=(
            "Notification listener pool name. Multiple huber instances "
            "sharing a pool will load-balance messages between them."
        ),
    ),
]

handlers_opts = [
    cfg.ListOpt(
        "enabled",
        default=[],
        help=(
            "List of handler names (huber.handler entry points) to load. "
            "A notification is dispatched to a handler when its event_type "
            "matches one of the handler's declared patterns."
        ),
    ),
]

cfg.CONF.register_opts(default_opts)
cfg.CONF.register_opts(worker_opts, group="worker")
cfg.CONF.register_opts(notification_opts, group="notification")
cfg.CONF.register_opts(handlers_opts, group="handlers")

logging.register_options(cfg.CONF)

oslo_messaging.set_transport_defaults(control_exchange="huber")

ks_loading.register_auth_conf_options(cfg.CONF, "service_auth")
ks_loading.register_session_conf_options(cfg.CONF, "service_auth")


def init(args=None, conf_file="/etc/huber/huber.conf"):
    args = args if args is not None else []
    cfg.CONF(args, project="huber", default_config_files=[conf_file])


def setup_logging(conf):
    """Sets up the logging options for a log with supplied name.

    :param conf: a cfg.ConfOpts object
    """
    product_name = "huber"

    logging.setup(conf, product_name)
    LOG.info("Logging enabled!")
    LOG.debug("command line: %s", " ".join(sys.argv))


# Used by oslo-config-generator entry point
# https://docs.openstack.org/oslo.config/latest/cli/generator.html
def list_opts():
    return [
        ("DEFAULT", default_opts),
        ("worker", worker_opts),
        ("notification", notification_opts),
        ("handlers", handlers_opts),
        add_auth_opts(),
    ]


def add_auth_opts():
    opts = ks_loading.register_session_conf_options(cfg.CONF, "service_auth")
    opt_list = copy.deepcopy(opts)
    opt_list.insert(0, ks_loading.get_auth_common_conf_options()[0])
    for plugin_option in ks_loading.get_auth_plugin_conf_options("password"):
        if all(option.name != plugin_option.name for option in opt_list):
            opt_list.append(plugin_option)
    opt_list.sort(key=operator.attrgetter("name"))
    return ("service_auth", opt_list)
