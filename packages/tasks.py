"""Immutable task specifications and explicit release-stage registry."""

from dataclasses import asdict, dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    entity: str
    stage: str
    positive: str
    graph_family: str

    @property
    def trainable(self) -> bool:
        return self.stage == "trainable"


TASK_REGISTRY = MappingProxyType({
    "phishing": TaskSpec("phishing", "address", "trainable", "phishing_address", "address_flow"),
    "ponzi": TaskSpec("ponzi", "contract", "trainable", "ponzi_contract", "address_flow"),
    "honeypot": TaskSpec("honeypot", "token", "trainable", "honeypot_sell_restriction", "token_v2"),
    "rug_pull": TaskSpec("rug_pull", "token", "trainable", "rug_pull_liquidity_v2", "token_v2"),
})
TASKS = MappingProxyType({name: MappingProxyType({k: v for k, v in asdict(spec).items() if k != "task_id"}) for name, spec in TASK_REGISTRY.items()})
ALIASES = {
    "phishing_address": "phishing", "ponzi_contract": "ponzi",
    "honeypot_sell_restriction": "honeypot", "rug_pull_liquidity_v2": "rug_pull",
    "rug-pull": "rug_pull", "rugpull": "rug_pull",
}


def canonical_task(task: str) -> str:
    task = ALIASES.get(task, task)
    if task not in TASK_REGISTRY:
        raise ValueError(f"Unsupported task {task!r}; choose {', '.join(TASK_REGISTRY)}")
    return task


def get_task(task: str) -> TaskSpec:
    return TASK_REGISTRY[canonical_task(task)]


def task_spec(task: str) -> dict:
    return asdict(get_task(task))
