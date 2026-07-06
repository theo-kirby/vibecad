# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.get_report_view_errors``."""

from __future__ import annotations
from VibeCADTransactions import report_view_error_summary


TOOL_SPEC = {'description': 'Return report-view errors, exceptions, and tracebacks that are NEW '
                'since the last check (consumed once read, including by transaction '
                'results). Set include_stale=true to re-read earlier errors.',
 'name': 'core.get_report_view_errors',
 'parameters': {'properties': {'include_stale': {'description': 'When true, also return '
                'errors already reported by earlier checks or transaction '
                'results, not just new ones. Default false.',
                'type': 'boolean'}},
                'type': 'object'},
 'safety': 'READ'}


def run(service, include_stale=False, **kwargs):
    return report_view_error_summary(include_stale=bool(include_stale))
