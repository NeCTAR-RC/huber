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

from oslo_log import log as logging
import oslo_messaging as messaging

from huber.notification import event as event_mod


LOG = logging.getLogger(__name__)


class NotificationEndpoint:
    """ceilometer event-pipeline endpoint.

    ceilometer's pipeline publishes events to a topic via the ``sample``
    priority — every message arrives at this method as a list of event
    dicts in the payload. The endpoint unwraps each event and asks the
    dispatcher to route it to handlers.
    """

    def __init__(self, dispatcher):
        self.dispatcher = dispatcher

    def sample(self, ctxt, publisher_id, event_type, payload, metadata):
        try:
            events = event_mod.from_ceilometer_payload(payload)
        except Exception:
            LOG.exception(
                "Unable to parse ceilometer payload from %s: %s",
                publisher_id,
                payload,
            )
            return messaging.NotificationResult.HANDLED

        for event in events:
            try:
                self.dispatcher.dispatch(event)
            except Exception:
                LOG.exception(
                    "Unhandled error dispatching event_type=%s message_id=%s",
                    event.event_type,
                    event.message_id,
                )
                # Always ack — re-queueing a poison message just loops.

        return messaging.NotificationResult.HANDLED
