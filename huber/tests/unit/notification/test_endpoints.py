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

from unittest import mock

import oslo_messaging as messaging

from huber.notification import endpoints
from huber.tests.unit import base as test_base


def _ceilometer_payload(event_type, traits=None, message_id="mid"):
    """Build a ceilometer-style notification payload."""
    return [
        {
            "event_type": event_type,
            "traits": traits or [],
            "message_signature": "sig",
            "raw": {},
            "generated": "2026-05-18T00:00:00",
            "message_id": message_id,
        }
    ]


class TestNotificationEndpoint(test_base.TestCase):
    def setUp(self):
        super().setUp()
        self.dispatcher = mock.Mock()
        self.endpoint = endpoints.NotificationEndpoint(self.dispatcher)

    def test_sample_unwraps_and_dispatches(self):
        payload = _ceilometer_payload(
            "compute.instance.create.end",
            traits=[
                ["instance_id", 1, "i-1"],
                ["project_id", 1, "p-1"],
            ],
        )
        result = self.endpoint.sample(
            ctxt={},
            publisher_id="ceilometer.publisher",
            event_type="event",
            payload=payload,
            metadata={"m": 1},
        )
        self.assertEqual(messaging.NotificationResult.HANDLED, result)
        self.dispatcher.dispatch.assert_called_once()
        event = self.dispatcher.dispatch.call_args[0][0]
        self.assertEqual("compute.instance.create.end", event.event_type)
        self.assertEqual(
            {"instance_id": "i-1", "project_id": "p-1"}, event.traits
        )
        self.assertEqual("mid", event.message_id)

    def test_sample_dispatches_each_event_in_batch(self):
        payload = _ceilometer_payload(
            "compute.instance.create.end", message_id="a"
        ) + _ceilometer_payload("compute.instance.delete.end", message_id="b")
        self.endpoint.sample({}, "pub", "event", payload, {})
        self.assertEqual(2, self.dispatcher.dispatch.call_count)

    def test_dispatcher_exception_is_swallowed(self):
        self.dispatcher.dispatch.side_effect = RuntimeError("boom")
        result = self.endpoint.sample(
            ctxt={},
            publisher_id="ceilometer.publisher",
            event_type="event",
            payload=_ceilometer_payload("x.y.z"),
            metadata={},
        )
        # We never want to re-queue: messages must always be acked.
        self.assertEqual(messaging.NotificationResult.HANDLED, result)

    def test_malformed_payload_is_swallowed(self):
        result = self.endpoint.sample(
            ctxt={},
            publisher_id="ceilometer.publisher",
            event_type="event",
            payload="not-a-list",
            metadata={},
        )
        self.assertEqual(messaging.NotificationResult.HANDLED, result)
        self.dispatcher.dispatch.assert_not_called()
