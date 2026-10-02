"""Link and unlink the treatment's cloud patient in one place.

A PIN lookup, a staff-saved patient and a phone sign-in all attach a
validated patient to the Treatment view; logout and replacement entry
detach it. These helpers keep those steps identical for every caller.
"""

from typing import Any, Dict, Optional

from helpers.cloud_contract import patient_label


def link_patient(window: Any, patient: Dict[str, Any], values: Dict[str, float],
                 protocol: int, name: Optional[str] = None) -> None:
    """Show a validated patient's whole plan, then link the patient."""
    view = window.shell.treatment
    view.set_settings(values)
    view.select_protocol(protocol)
    window.cloud_patient = patient
    view.set_patient(name or patient_label(patient))


def unlink_patient(window: Any) -> None:
    """Detach the linked patient and invalidate any lookup still in flight."""
    window._patient_lookup_id += 1
    window.cloud_patient = None
    window._patient_lookup_pending = False
    view = window.shell.treatment
    view.set_patient_pending(False)
    view.clear_patient()
