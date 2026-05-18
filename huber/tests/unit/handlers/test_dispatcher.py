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

from huber.common import exceptions
from huber.handlers import base
from huber.handlers import dispatcher as dispatcher_mod
from huber.notification import event as event_mod
from huber.tests.unit import base as test_base


def _event(event_type, traits=None):
    return event_mod.Event(
        event_type=event_type,
        traits=traits or {},
        message_id="mid",
        generated="2026-05-18T00:00:00",
        raw_payload={},
    )


class _RecordingHandler(base.HandlerBase):
    event_types = ["compute.instance.*"]

    def __init__(self):
        self.calls = []

    def handle(self, event):
        self.calls.append(event)


class _BoomHandler(base.HandlerBase):
    event_types = ["*"]

    def handle(self, event):
        raise RuntimeError("kaboom")


class TestDispatcher(test_base.TestCase):
    def _build(self, handlers):
        dispatcher = dispatcher_mod.Dispatcher.__new__(
            dispatcher_mod.Dispatcher
        )
        dispatcher.handler_names = [type(h).__name__ for h in handlers]
        dispatcher.handlers = handlers
        return dispatcher

    def test_dispatches_matching_handlers(self):
        h = _RecordingHandler()
        dispatcher = self._build([h])
        dispatcher.dispatch(_event("compute.instance.create.end"))
        self.assertEqual(1, len(h.calls))
        self.assertEqual("compute.instance.create.end", h.calls[0].event_type)

    def test_skips_non_matching_handlers(self):
        h = _RecordingHandler()
        dispatcher = self._build([h])
        dispatcher.dispatch(_event("network.port.create.end"))
        self.assertEqual([], h.calls)

    def test_failing_handler_does_not_block_others(self):
        recording = _RecordingHandler()
        dispatcher = self._build([_BoomHandler(), recording])
        dispatcher.dispatch(_event("compute.instance.create.end"))
        self.assertEqual(1, len(recording.calls))

    def test_missing_handler_raises(self):
        with mock.patch.object(
            dispatcher_mod.named, "NamedExtensionManager"
        ) as mgr:
            mgr.return_value = []
            self.assertRaises(
                exceptions.HandlerNotFound,
                dispatcher_mod.Dispatcher,
                ["does-not-exist"],
            )

    def test_no_handlers_configured_is_allowed(self):
        dispatcher = dispatcher_mod.Dispatcher([])
        self.assertEqual([], dispatcher.handlers)
        # Dispatching with no handlers loaded must not raise.
        dispatcher.dispatch(_event("anything.at.all"))

    def test_loads_logging_handler_from_entry_points(self):
        # The 'logging' handler is registered in this package's setup.cfg.
        # If the package isn't installed (e.g. during early bootstrap),
        # skip rather than fail.
        try:
            dispatcher = dispatcher_mod.Dispatcher(["logging"])
        except exceptions.HandlerNotFound:
            self.skipTest("huber not installed; entry points unavailable")
        self.assertEqual(1, len(dispatcher.handlers))
