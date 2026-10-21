"""Local JSON storage for the training plan, keeping every previous version."""

from pathlib import Path

from running_coach.domain.plan import Plan


class PlanStore:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.path = data_dir / "plan.json"

    def load(self) -> Plan | None:
        if not self.path.exists():
            return None
        return Plan.model_validate_json(self.path.read_text())

    def save(self, plan: Plan) -> Plan:
        """Save as the current plan, bumping the version and archiving the previous one."""
        self.dir.mkdir(parents=True, exist_ok=True)
        if previous := self.load():
            (self.dir / f"plan.v{previous.version}.json").write_text(self.path.read_text())
            plan = plan.model_copy(update={"version": previous.version + 1})
        self.path.write_text(plan.model_dump_json(indent=2))
        return plan
