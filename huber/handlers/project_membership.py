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


project_membership_opts = [
    cfg.StrOpt(
        "subject",
        default="Nectar project role change",
        help=(
            "Subject prefix for taynac messages sent by this handler. The "
            "affected project's name is appended, giving a subject like "
            "'Nectar project role change: my-project'."
        ),
    ),
    cfg.StrOpt(
        "tenantmanager_role",
        default="tenantmanager",
        help=(
            "Name of the keystone role that identifies a project's "
            "tenant managers. Assignment changes for this role trigger "
            "a notification, and users holding it count towards the "
            "minimum of two recipients required to send. Should match "
            "taynac's [identity] manager_role. Compared case-"
            "insensitively against role names from keystone."
        ),
    ),
    cfg.StrOpt(
        "member_role",
        default="member",
        help=(
            "Name of the keystone role that identifies ordinary project "
            "members. Assignment changes for this role trigger a "
            "notification, and users holding it count towards the "
            "minimum of two recipients required to send. Should match "
            "taynac's [identity] member_role. Compared case-"
            "insensitively."
        ),
    ),
    cfg.StrOpt(
        "reader_role",
        default="reader",
        help=(
            "Name of the keystone role that identifies read-only project "
            "members. Compared case-insensitively against role names "
            "from keystone."
        ),
    ),
]
cfg.CONF.register_opts(project_membership_opts, group="project_membership")


CREATED_EVENT = "identity.role_assignment.created"
DELETED_EVENT = "identity.role_assignment.deleted"


class ProjectMembershipHandler(common.TaynacHandlerBase):
    """Notify a project's tenant manager when membership changes.

    Triggered by keystone's ``identity.role_assignment.created`` and
    ``identity.role_assignment.deleted`` notifications. For each event we:

    1. Resolve the affected user/group, project, and role via keystone.
       Only the tenantmanager, member, and reader roles are notifiable;
       events for any other role are ignored.
    2. Build a table of the project's current members (effective
       assignments — group memberships are expanded to users) for the
       message body.
    3. Send **one** taynac message with the project's id; taynac resolves
       the recipients itself (first tenant manager as recipient, other
       tenant managers and members CC'd).

    If fewer than two users would be notified (counting enabled
    tenantmanager/member users with an email), no message is sent.
    """

    event_types = [CREATED_EVENT, DELETED_EVENT]

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
        role = ks.roles.get(role_id) if role_id else None
        role_name = getattr(role, "name", None) if role else None
        notifiable_roles = (
            CONF.project_membership.tenantmanager_role.lower(),
            CONF.project_membership.member_role.lower(),
            CONF.project_membership.reader_role.lower(),
        )
        if not role_name or role_name.lower() not in notifiable_roles:
            LOG.debug(
                "Skipping %s (message_id=%s): role %s is not a "
                "notifiable role",
                event.event_type,
                event.message_id,
                role_name or role_id,
            )
            return

        project = ks.projects.get(project_id)

        if target_user_id:
            target = ks.users.get(target_user_id)
            target_kind = "user"
        else:
            target = ks.groups.get(target_group_id)
            target_kind = "group"

        members_table = self._members_table(ks, project_id)

        # Taynac notifies the project's tenantmanager/member users. If
        # fewer than two of them could receive email, keep the historical
        # behaviour of not sending at all.
        recipient_roles = {
            CONF.project_membership.tenantmanager_role.lower(),
            CONF.project_membership.member_role.lower(),
        }
        recipients = sum(
            1
            for row in members_table
            if row["email"]
            and recipient_roles & {r.lower() for r in row["roles"]}
        )
        if recipients < 2:
            LOG.debug(
                "Skipping %s (message_id=%s): fewer than two users would "
                "be notified",
                event.event_type,
                event.message_id,
            )
            return

        project_name = getattr(project, "name", project_id)

        body = self.render(
            f"project_membership/{action}.html",
            target_name=common.display_name(target),
            target_kind=target_kind,
            project_name=project_name,
            role_name=role_name,
            members_table=members_table,
        )

        subject = f"{CONF.project_membership.subject}: {project_name}"

        try:
            msg = taynac.messages.send(
                subject=subject,
                body=body,
                project_id=project_id,
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
            getattr(msg, "recipient", None),
            len(getattr(msg, "cc", None) or []),
            getattr(msg, "backend_id", None),
            project_id,
            target.id,
        )

    @staticmethod
    def _members_table(ks, project_id):
        """Single pass over the project's effective role assignments.

        Returns a list of ``{"name", "email", "roles"}`` dicts covering
        every enabled user holding any role on the project, sorted by
        display name. ``roles`` is the deduped list of role names.
        """
        role_names = {}  # role_id -> role.name (original case)
        user_to_role_ids = {}  # user_id -> set of role_ids

        for a in ks.role_assignments.list(project=project_id, effective=True):
            role_ref = getattr(a, "role", None)
            user_ref = getattr(a, "user", None)
            if not role_ref or not user_ref:
                continue
            role_id = common.ref_id(role_ref)
            user_id = common.ref_id(user_ref)
            if not role_id or not user_id:
                continue

            if role_id not in role_names:
                role_names[role_id] = ks.roles.get(role_id).name

            user_to_role_ids.setdefault(user_id, set()).add(role_id)

        # Fetch each user once.
        user_cache = {uid: ks.users.get(uid) for uid in user_to_role_ids}

        members_table = []
        for uid, rids in user_to_role_ids.items():
            user = user_cache[uid]
            # Disabled keystone users shouldn't be listed. Default to
            # enabled when the attribute is missing.
            if not getattr(user, "enabled", True):
                continue
            members_table.append(
                {
                    "name": common.display_name(user),
                    "email": getattr(user, "email", "") or "",
                    "roles": sorted({role_names[rid] for rid in rids}),
                }
            )
        members_table.sort(key=lambda row: row["name"].lower())

        return members_table
