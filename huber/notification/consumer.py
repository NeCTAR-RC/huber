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

import cotyledon
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging

from huber.handlers import dispatcher as dispatcher_mod
from huber.notification import endpoints


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ConsumerService(cotyledon.Service):
    def __init__(self, worker_id, conf):
        super().__init__(worker_id)
        self.conf = conf
        self.message_listener = None

    def run(self):
        LOG.info(
            "Starting huber notification consumer on %s:%s (pool=%s)",
            CONF.notification.exchange,
            CONF.notification.topic,
            CONF.notification.pool,
        )
        transport = messaging.get_notification_transport(CONF)
        targets = [
            messaging.Target(
                exchange=CONF.notification.exchange,
                topic=CONF.notification.topic,
            )
        ]
        dispatcher = dispatcher_mod.Dispatcher()
        endpoint = endpoints.NotificationEndpoint(dispatcher)
        self.message_listener = messaging.get_notification_listener(
            transport,
            targets,
            [endpoint],
            executor="threading",
            pool=CONF.notification.pool,
        )
        self.message_listener.start()

    def terminate(self):
        if self.message_listener:
            LOG.info("Stopping consumer...")
            self.message_listener.stop()
            LOG.info(
                "Consumer successfully stopped. Waiting for "
                "final messages to be processed..."
            )
            self.message_listener.wait()
        super().terminate()
