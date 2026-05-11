"""Finite-state machine states for the conversational backup flow.

The backup flow is modelled as a linear sequence of states managed by
aiogram 3.x ``FSMContext`` with Redis-backed storage.
"""

from aiogram.fsm.state import State, StatesGroup


class BackupStates(StatesGroup):
    """States for the /backup conversational wizard.

    Transitions
    -----------
    idle → selecting_backup_type
        Triggered by ``/backup`` command.
    selecting_backup_type → selecting_databases
        Triggered by "custom" callback.
    selecting_backup_type → confirming
        Triggered by "full" callback (skips DB / collection selection).
    selecting_databases → selecting_collections
        Triggered by "continuar" callback after DB selection.
    selecting_collections → confirming
        Triggered by "confirmar" callback after collection selection.
    confirming → idle
        Triggered by "ejecutar" (success) or "cancelar" (aborted).
    any → idle
        Triggered by timeout or explicit ``/cancel``.
    """

    idle = State(state="idle")
    selecting_backup_type = State(state="selecting_backup_type")
    selecting_databases = State(state="selecting_databases")
    selecting_collections = State(state="selecting_collections")
    confirming = State(state="confirming")
    executing = State(state="executing")
