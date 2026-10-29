"""In-process, same-database paper receiver; never sends to an exchange or network."""
from signal_desk.paper.ledger import PaperLedger


class LocalPaperReceiver:
    """Own connection enforces the persisted writer fence at acceptance time."""

    def __init__(self, path):
        self._ledger = PaperLedger.open(path)

    def accept(self, envelope, *, accepted_at):
        return self._ledger.accept_local(envelope, accepted_at=accepted_at)

    def close(self):
        self._ledger.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
