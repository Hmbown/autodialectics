class Scratchpad:
    def __init__(self) -> None:
        self._entries: list[dict] = []

    def add(self, key: str, value: str, evidence_ids: list[str] | None = None) -> None:
        self._entries.append({"key": key, "value": value, "evidence_ids": evidence_ids or []})

    def to_dict(self) -> dict:
        return {"entries": self._entries}


class MemoryManager:
    def __init__(self, contract) -> None:
        self.contract = contract
        self.scratchpad = Scratchpad()
        self.distilled: list[str] = []

    def hygiene_report(self) -> dict:
        return {
            "scratchpad_entries": len(self.scratchpad._entries),
            "distilled_learnings": len(self.distilled),
            "contract_id": getattr(self.contract, "contract_id", "unknown"),
        }
