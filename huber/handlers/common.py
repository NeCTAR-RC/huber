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

"""Shared helpers for handlers that talk to keystone and taynac."""

import os

import jinja2

from huber.common import clients
from huber.common import keystone
from huber.handlers import base


TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


def ref_id(ref):
    """Extract an id from a keystone ``{'id': ...}`` dict or scalar."""
    if isinstance(ref, dict):
        return ref.get("id")
    return ref


def display_name(obj):
    """Best-effort human-readable name for a keystone user or group."""
    for attr in ("full_name", "name", "id"):
        value = getattr(obj, attr, None)
        if value:
            return value
    return "(unknown)"


class TaynacHandlerBase(base.HandlerBase):
    """Base for handlers that render a jinja template and send via taynac.

    Provides lazy keystone/taynac client construction so the handler can be
    imported without a live keystone — useful for tests and config
    generation — plus a shared jinja environment rooted at the package
    ``templates/`` directory.
    """

    def __init__(self):
        self._session = None
        self._ks = None
        self._taynac = None
        self._jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
            autoescape=jinja2.select_autoescape(["html", "tmpl"]),
        )

    def _clients(self):
        if self._ks is None:
            self._session = keystone.KeystoneSession().get_session()
            self._ks = clients.get_keystoneclient(self._session)
            self._taynac = clients.get_taynacclient(self._session)
        return self._ks, self._taynac

    def render(self, template_path, **context):
        return self._jinja.get_template(template_path).render(**context)
