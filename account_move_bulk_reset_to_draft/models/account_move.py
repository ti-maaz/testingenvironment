import logging

from odoo import _, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_bulk_reset_to_draft(self):
        return self._run_bulk_move_action(
            action_title=_("Bulk Reset to Draft"),
            success_label=_("Reset to draft"),
            include_already_draft=True,
            operation=self._bulk_reset_single_move_to_draft,
        )

    def action_bulk_reset_to_draft_and_delete(self):
        return self._run_bulk_move_action(
            action_title=_("Bulk Reset to Draft and Delete"),
            success_label=_("Deleted"),
            include_already_draft=False,
            operation=self._bulk_reset_single_move_to_draft_and_delete,
        )

    def _run_bulk_move_action(self, action_title, success_label, include_already_draft, operation):
        """Run a bulk journal-entry action one move at a time with isolated savepoints."""
        self._check_bulk_move_action_access()

        moves = self._get_bulk_action_moves()
        if not moves:
            return self._bulk_move_action_notification(
                action_title=action_title,
                success_label=success_label,
                total_count=0,
                success_count=0,
                already_draft_names=[],
                failures=[],
                include_already_draft=include_already_draft,
            )

        success_count = 0
        already_draft_names = []
        failures = []

        for move in moves:
            move_name = self._get_bulk_move_action_name(move)

            if move.move_type != 'entry':
                failures.append((
                    move_name,
                    _("Only journal entries can be processed by this action."),
                ))
                continue

            try:
                result = operation(move)
            except (AccessError, UserError, ValidationError) as err:
                failures.append((move_name, self._bulk_reset_to_draft_reason(err)))
            except Exception as err:  # pragma: no cover - defensive logging for unexpected failures
                _logger.exception(
                    "Unexpected error while processing account.move %s in bulk action '%s'.",
                    move.id,
                    action_title,
                )
                failures.append((move_name, self._bulk_reset_to_draft_reason(err)))
            else:
                if result == 'already_draft':
                    already_draft_names.append(move_name)
                elif result == 'success':
                    success_count += 1

        return self._bulk_move_action_notification(
            action_title=action_title,
            success_label=success_label,
            total_count=len(moves),
            success_count=success_count,
            already_draft_names=already_draft_names,
            failures=failures,
            include_already_draft=include_already_draft,
        )

    def _bulk_reset_single_move_to_draft(self, move):
        if move.state == 'draft':
            return 'already_draft'

        with self.env.cr.savepoint():
            move.button_draft()
        return 'success'

    def _bulk_reset_single_move_to_draft_and_delete(self, move):
        with self.env.cr.savepoint():
            if move.state in ('posted', 'cancel'):
                move.button_draft()
            move.unlink()
        return 'success'

    def _bulk_move_action_notification(
        self,
        action_title,
        success_label,
        total_count,
        success_count,
        already_draft_names,
        failures,
        include_already_draft,
    ):
        already_draft_count = len(already_draft_names)
        failed_count = len(failures)

        summary = " | ".join([
            _("Selected: %(count)s", count=total_count),
            _("%(label)s: %(count)s", label=success_label, count=success_count),
            _("Failed: %(count)s", count=failed_count),
        ])
        if include_already_draft:
            summary = "%s | %s" % (
                summary,
                _("Already in draft: %(count)s", count=already_draft_count),
            )

        details = []
        if include_already_draft and already_draft_names:
            details.append(
                _("Already in draft: %(moves)s", moves=", ".join(already_draft_names))
            )
        if failures:
            failure_lines = "; ".join(
                _("%(move)s (%(reason)s)", move=move_name, reason=reason)
                for move_name, reason in failures
            )
            details.append(_("Failed entries: %(details)s", details=failure_lines))

        message = summary if not details else "%s\n%s" % (summary, "\n".join(details))

        if not total_count:
            notification_type = 'warning'
        elif failed_count and not success_count and not already_draft_count:
            notification_type = 'danger'
        elif failed_count:
            notification_type = 'warning'
        else:
            notification_type = 'success'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': action_title,
                'message': message,
                'type': notification_type,
                'sticky': bool(failed_count),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def _check_bulk_move_action_access(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_("Only Accounting Managers can use these bulk journal-entry actions."))

    def _get_bulk_action_moves(self):
        active_ids = list(dict.fromkeys(self.env.context.get('active_ids') or self.ids))
        return self.browse(active_ids).exists()

    @staticmethod
    def _get_bulk_move_action_name(move):
        move_name = move.name if move.name and move.name != '/' else move.display_name
        return move_name or _("Journal Entry ID %(id)s", id=move.id)

    @staticmethod
    def _bulk_reset_to_draft_reason(error):
        message = str(getattr(error, 'name', error) or '').strip()
        return " ".join(message.split()) or _("Unknown error")
