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

from huber.handlers import logging_handler
from huber.notification import event as event_mod
from huber.tests.unit import base as test_base


class TestLoggingHandler(test_base.TestCase):
    def test_matches_everything(self):
        h = logging_handler.LoggingHandler()
        self.assertTrue(h.matches("compute.instance.create.end"))
        self.assertTrue(h.matches("anything"))

    def test_handle_logs(self):
        h = logging_handler.LoggingHandler()
        event = event_mod.Event(
            event_type="compute.instance.create.end",
            traits={"instance_id": "abc"},
            message_id="mid",
            generated="2026-05-18T00:00:00",
            raw_payload={},
        )
        with mock.patch.object(logging_handler, "LOG") as log:
            h.handle(event)
        log.info.assert_called_once()
