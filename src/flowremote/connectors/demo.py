"""Target connectors. Every implementation in this package is simulated.

A connector is the only place that is allowed to talk to an external system.
Keeping the seam here means the day a real OA or BI adapter arrives, the routes
and the engine do not change: they keep calling ``write`` and ``sync``.

Nothing in this package opens a socket. ``SimulatedTarget.write`` returns the
number it was handed, immediately.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimulatedTarget:
    """Stands in for an OA or BI endpoint during the demonstration.

    ``role`` is the word the approval screen shows: "primary" writes the
    records, "secondary" syncs the same records and never makes a second copy
    (BR-5).
    """

    name: str
    role: str

    def write(self, count: int) -> int:
        """Pretend to write ``count`` records and report how many were accepted."""
        if count < 0:
            raise ValueError("cannot write a negative number of records")
        return count

    def sync(self, count: int) -> int:
        """Pretend to sync the same records to the secondary target."""
        return self.write(count)


class SimulatedFailure(SimulatedTarget):
    """A target that refuses the record at position ``fail_at`` (1-based).

    Used only to demonstrate and test the partial-failure path; the run stops at
    the record before the failure instead of claiming it was written.
    """

    fail_at: int | None = None

    def write(self, count: int) -> int:
        if self.fail_at is not None and self.fail_at <= count:
            raise RuntimeError(f"simulated write failure at record {self.fail_at}")
        return count
