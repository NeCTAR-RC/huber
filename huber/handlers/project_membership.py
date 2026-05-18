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

import os

import jinja2
from oslo_config import cfg
from oslo_log import log as logging

from huber.common import clients
from huber.common import keystone
from huber.handlers import base


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


project_membership_opts = [
    cfg.StrOpt(
        "subject",
        default="Nectar project role change",
        help="Subject line for taynac messages sent by this handler.",
    ),
    cfg.StrOpt(
        "tenantmanager_role",
        default="tenantmanager",
        help=(
            "Name of the keystone role that identifies a project's "
            "tenant managers. The first user holding this role is used "
            "as the message's primary recipient. Compared case-"
            "insensitively against role names from keystone."
        ),
    ),
    cfg.StrOpt(
        "member_role",
        default="member",
        help=(
            "Name of the keystone role that identifies ordinary project "
            "members. Users with this role (and tenantmanagers) are CC'd "
            "on the notification. Compared case-insensitively."
        ),
    ),
]
cfg.CONF.register_opts(project_membership_opts, group="project_membership")


CREATED_EVENT = "identity.role_assignment.created"
DELETED_EVENT = "identity.role_assignment.deleted"


class ProjectMembershipHandler(base.HandlerBase):
    """Notify a project's tenant manager when membership changes.

    Triggered by keystone's ``identity.role_assignment.created`` and
    ``identity.role_assignment.deleted`` notifications. For each event we:

    1. Resolve the affected user/group, project, and role via keystone.
    2. Find the project's tenant managers and ordinary members (effective
       assignments — group memberships are expanded to users).
    3. Send **one** taynac message:
        * ``recipient`` = first tenant manager (by keystone API order)
        * ``cc`` = every other user holding the tenantmanager or member
          role on the project
    """

    event_types = [CREATED_EVENT, DELETED_EVENT]

    TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

    def __init__(self):
        self._session = None
        self._ks = None
        self._taynac = None
        self._jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(self.TEMPLATE_DIR),
            autoescape=jinja2.select_autoescape(["html", "tmpl"]),
        )

    # Lazy client construction so the handler can be imported without a
    # live keystone — useful for tests and config generation.
    def _clients(self):
        if self._ks is None:
            self._session = keystone.KeystoneSession().get_session()
            self._ks = clients.get_keystoneclient(self._session)
            self._taynac = clients.get_taynacclient(self._session)
        return self._ks, self._taynac

    def handle(self, event):
        action = "added" if event.event_type == CREATED_EVENT else "removed"

        project_id = event.traits.get("project")
        if not project_id:
            LOG.debug(
                "Skipping %s (message_id=%s): no project trait "
                "(domain-scoped assignment?)",
                event.event_type,
                event.message_id,
            )
            return

        target_user_id = event.traits.get("user")
        target_group_id = event.traits.get("group")
        if not target_user_id and not target_group_id:
            LOG.debug(
                "Skipping %s (message_id=%s): no user or group trait",
                event.event_type,
                event.message_id,
            )
            return

        role_id = event.traits.get("role")

        ks, taynac = self._clients()
        project = ks.projects.get(project_id)
        role = ks.roles.get(role_id) if role_id else None

        if target_user_id:
            target = ks.users.get(target_user_id)
            target_kind = "user"
        else:
            target = ks.groups.get(target_group_id)
            target_kind = "group"

        tenantmanagers, cc_users = self._collect_audience(ks, project_id)
        if not tenantmanagers:
            LOG.warning(
                "No %s on project %s; skipping %s notification "
                "(message_id=%s)",
                CONF.project_membership.tenantmanager_role,
                project_id,
                event.event_type,
                event.message_id,
            )
            return

        primary = tenantmanagers[0]
        primary_email = getattr(primary, "email", None)
        if not primary_email:
            LOG.warning(
                "Primary tenant manager %s has no email; skipping %s "
                "notification (message_id=%s)",
                primary.id,
                event.event_type,
                event.message_id,
            )
            return

        cc_emails = sorted(
            {
                u.email
                for u in cc_users
                if getattr(u, "email", None) and u.id != primary.id
            }
        )

        template = self._jinja.get_template(
            f"project_membership/{action}.html"
        )
        body = template.render(
            recipient_name=_display_name(primary),
            target_name=_display_name(target),
            target_kind=target_kind,
            project_name=getattr(project, "name", project_id),
            role_name=getattr(role, "name", None) if role else None,
        )

        try:
            msg = taynac.messages.send(
                subject=CONF.project_membership.subject,
                body=body,
                recipient=primary_email,
                cc=cc_emails,
            )
        except Exception:
            LOG.exception(
                "Failed sending taynac message for %s (project=%s, target=%s)",
                event.event_type,
                project_id,
                target.id,
            )
            return

        LOG.info(
            "Sent project-membership %s message: to=%s cc=%d "
            "(backend_id=%s, project=%s, target=%s)",
            action,
            primary_email,
            len(cc_emails),
            getattr(msg, "backend_id", None),
            project_id,
            target.id,
        )

    @staticmethod
    def _collect_audience(ks, project_id):
        """Return ``(tenantmanagers, cc_users)`` as keystone User objects.

        ``tenantmanagers`` preserves the order keystone returned the
        assignments in, so ``[0]`` is deterministic relative to keystone.
        ``cc_users`` contains every user holding the tenantmanager or
        member role on the project, deduplicated by id.
        """
        tm_name = CONF.project_membership.tenantmanager_role.lower()
        member_name = CONF.project_membership.member_role.lower()

        role_names = {}
        tenantmanager_ids = []
        cc_ids = set()

        for a in ks.role_assignments.list(project=project_id, effective=True):
            role_ref = getattr(a, "role", None)
            user_ref = getattr(a, "user", None)
            if not role_ref or not user_ref:
                continue
            role_id = _ref_id(role_ref)
            user_id = _ref_id(user_ref)
            if not role_id or not user_id:
                continue

            if role_id not in role_names:
                role_names[role_id] = ks.roles.get(role_id).name
            name = role_names[role_id].lower()

            if name == tm_name:
                if user_id not in tenantmanager_ids:
                    tenantmanager_ids.append(user_id)
                cc_ids.add(user_id)
            elif name == member_name:
                cc_ids.add(user_id)

        user_cache = {uid: ks.users.get(uid) for uid in cc_ids}
        tenantmanagers = [user_cache[uid] for uid in tenantmanager_ids]
        cc_users = list(user_cache.values())
        return tenantmanagers, cc_users


def _ref_id(ref):
    """Extract an id from a keystone {'id': ...} dict or scalar."""
    if isinstance(ref, dict):
        return ref.get("id")
    return ref


def _display_name(obj):
    """Best-effort human-readable name for a keystone user or group."""
    for attr in ("full_name", "name", "id"):
        value = getattr(obj, attr, None)
        if value:
            return value
    return "(unknown)"
