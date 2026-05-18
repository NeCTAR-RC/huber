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

from oslo_config import cfg
from oslo_log import log as logging
from stevedore import named

from huber.common import exceptions


CONF = cfg.CONF
LOG = logging.getLogger(__name__)

NAMESPACE = "huber.handler"


class Dispatcher:
    """Loads enabled handlers and routes events to them."""

    def __init__(self, handler_names=None):
        if handler_names is None:
            handler_names = CONF.handlers.enabled
        self.handler_names = list(handler_names)
        self.handlers = self._load_handlers(self.handler_names)

    @staticmethod
    def _load_handlers(names):
        if not names:
            LOG.warning(
                "No handlers configured in [handlers] enabled; "
                "huber will receive notifications but do nothing."
            )
            return []

        mgr = named.NamedExtensionManager(
            namespace=NAMESPACE,
            names=names,
            name_order=True,
            invoke_on_load=True,
            on_load_failure_callback=Dispatcher._on_load_failure,
        )
        loaded = [ext.name for ext in mgr]
        missing = [n for n in names if n not in loaded]
        if missing:
            raise exceptions.HandlerNotFound(
                f"Handlers not found in '{NAMESPACE}': {missing}"
            )
        LOG.info("Loaded handlers: %s", loaded)
        return [ext.obj for ext in mgr]

    @staticmethod
    def _on_load_failure(manager, entrypoint, exception):
        LOG.error("Failed to load handler %s: %s", entrypoint, exception)
        raise exception

    def dispatch(self, event):
        """Run every matching handler for one Event.

        Handlers run in the order listed in ``[handlers] enabled``. A
        failure in one handler is logged but does not prevent the others
        from running.
        """
        for handler in self.handlers:
            if not handler.matches(event.event_type):
                continue
            handler_name = type(handler).__name__
            LOG.debug(
                "Dispatching %s to handler %s",
                event.event_type,
                handler_name,
            )
            try:
                handler.handle(event)
            except Exception:
                LOG.exception(
                    "Handler %s raised while processing %s",
                    handler_name,
                    event.event_type,
                )
