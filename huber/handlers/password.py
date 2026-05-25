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

from huber.handlers import common


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


password_opts = [
    cfg.StrOpt(
        "subject",
        default="Your Nectar password has been changed",
        help="Subject line for taynac messages sent by this handler.",
    ),
]
cfg.CONF.register_opts(password_opts, group="password")


UPDATED_EVENT = "identity.user.updated"

# CADF actions keystone emits when a password is changed or reset. The
# self-service `/v3/users/{id}/password` endpoint emits `update/password`;
# the admin reset path (PATCH /v3/users/{id} with a new password) typically
# emits a plain `update` action with `password_expires_at` among the
# changed fields.
PASSWORD_ACTIONS = frozenset(["update/password"])


class PasswordHandler(common.TaynacHandlerBase):
    """Notify a user when their keystone password is changed or reset.

    Triggered by keystone's ``identity.user.updated`` notification. Only
    fires when the CADF ``action`` trait identifies the update as a
    password operation (self-service or admin reset) — other user updates
    (name, email, …) are ignored.
    """

    event_types = [UPDATED_EVENT]

    def handle(self, event):
        action = event.traits.get("action")
        if action not in PASSWORD_ACTIONS:
            LOG.debug(
                "Skipping %s (message_id=%s): action=%s is not a "
                "password update",
                event.event_type,
                event.message_id,
                action,
            )
            return

        target_user_id = (
            event.traits.get("target_user_id")
            or event.traits.get("resource_id")
            or event.traits.get("user")
        )
        if not target_user_id:
            LOG.debug(
                "Skipping %s (message_id=%s): no target user trait",
                event.event_type,
                event.message_id,
            )
            return

        initiator_id = event.traits.get("initiator_id") or event.traits.get(
            "initiator_user_id"
        )

        ks, taynac = self._clients()
        user = ks.users.get(target_user_id)

        if not getattr(user, "enabled", True):
            LOG.info(
                "Skipping password notification for disabled user %s "
                "(message_id=%s)",
                user.id,
                event.message_id,
            )
            return

        email = getattr(user, "email", None)
        if not email:
            LOG.warning(
                "User %s has no email; skipping password notification "
                "(message_id=%s)",
                user.id,
                event.message_id,
            )
            return

        self_service = bool(initiator_id) and initiator_id == user.id

        body = self.render(
            "password/changed.html",
            recipient_name=common.display_name(user),
            self_service=self_service,
        )

        try:
            msg = taynac.messages.send(
                subject=CONF.password.subject,
                body=body,
                recipient=email,
            )
        except Exception:
            LOG.exception(
                "Failed sending taynac password message for user %s "
                "(message_id=%s)",
                user.id,
                event.message_id,
            )
            return

        LOG.info(
            "Sent password-change message: to=%s (backend_id=%s, user=%s)",
            email,
            getattr(msg, "backend_id", None),
            user.id,
        )
