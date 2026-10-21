"""Local JSON storage for the athlete profile.

Phase 0 keeps this deliberately simple; SQLite replaces it once plans and
activity logs arrive.
"""

from pathlib import Path

from running_coach.domain.athlete import AthleteProfile


class ProfileStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "profile.json"

    def load(self) -> AthleteProfile:
        if not self.path.exists():
            return AthleteProfile()
        return AthleteProfile.model_validate_json(self.path.read_text())

    def save(self, profile: AthleteProfile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(profile.model_dump_json(indent=2))
