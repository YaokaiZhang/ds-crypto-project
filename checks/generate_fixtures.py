"""Generate explicitly synthetic examples; never fetch data or train a model."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def generate(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    cutoff = 1700000000
    targets, raw, labels = [], [], []
    def addr(number):
        return "0x" + format(number, "040x")
    def txhash(number):
        return "0x" + format(number, "064x")
    for task_number, task in enumerate(("phishing", "ponzi"), 1):
        for i in range(20):
            root = addr(task_number * 1000 + i)
            other = addr(10000 + task_number * 1000 + i)
            targets.append({"sample_id": f"synthetic-{task}-{i}", "task_id": task, "target": root,
                            "cutoff": cutoff, "chain_id": 1, "synthetic": True,
                            "coverage": {"complete": True, "observation_start": cutoff - 30 * 86400,
                                         "cutoff": cutoff, "neighborhood_history_complete": True},
                            "background_selected": task == "phishing" and i >= 10,
                            "cohort_id": "synthetic-background-v1" if task == "phishing" else None})
            label = "" if task == "phishing" and i >= 10 else int(i < 10)
            labels.append({"task_id": task, "entity_id": root, "mapped_label": label,
                           "label_status": "unlabeled" if label == "" else "supported_positive" if label else "supported_negative",
                           "role": "phishing_receiver" if task == "phishing" else "target_contract",
                           "audit_decision": "admitted", "valid_from": cutoff - 30 * 86400,
                           "valid_to": cutoff, "label_available_at": cutoff,
                           "evidence_ref": f"synthetic://fixture/{task}/{i}"})
            number = task_number * 1000 + i
            raw.append({"source_kind": "normal", "chainId": "1", "hash": txhash(number),
                        "from": other, "to": root, "value": str((i + 1) * 10**18), "input": "0x",
                        "timeStamp": str(cutoff - 3600), "blockNumber": str(18000000 + i),
                        "isError": "0", "synthetic": True})
            raw.append({"source_kind": "internal", "chainId": "1", "hash": txhash(number + 100000),
                        "from": root, "to": other, "value": str((i + 1) * 10**16), "traceId": "0_1",
                        "timeStamp": str(cutoff - 1800), "blockNumber": str(18000020 + i),
                        "isError": "0", "synthetic": True})
    # Fixed-width v2/Transfer logs to exercise the token data-only builders.
    from packages.transactions import TRANSFER_TOPIC, V2_TOPICS
    def topic_address(value):
        return "0x" + value[2:].rjust(64, "0")
    def words(*values):
        return "0x" + "".join(format(value, "064x") for value in values)
    for i, task in enumerate(("honeypot", "rug_pull")):
        token, pair, wallet, quote = addr(3000 + i), addr(4000 + i), addr(5000 + i), addr(6000 + i)
        targets.append({"sample_id": f"synthetic-{task}", "task_id": task, "target": token,
                        "cutoff": cutoff, "chain_id": 1, "pools": [pair], "synthetic": True,
                        "coverage": {"complete": True, "observation_start": cutoff - 30 * 86400,
                                     "cutoff": cutoff, "neighborhood_history_complete": True}})
        created = next(topic for topic, kind in V2_TOPICS.items() if kind == "pair_created")
        swap = next(topic for topic, kind in V2_TOPICS.items() if kind == "swap")
        logs = [
            {"address": addr(7000), "topics": [created, topic_address(token), topic_address(quote)],
             "data": words(int(pair, 16), 1)},
            {"address": token, "topics": [TRANSFER_TOPIC, topic_address(wallet), topic_address(pair)],
             "data": words(10**18)},
            {"address": pair, "topics": [swap, topic_address(wallet), topic_address(wallet)],
             "data": words(10**18, 0, 0, 10**16)},
        ]
        for index, log in enumerate(logs):
            raw.append({"source_kind": "logs", **log, "transactionHash": txhash(90000 + i),
                        "logIndex": hex(index), "blockNumber": hex(18000100 + i),
                        "timeStamp": hex(cutoff - 900), "synthetic": True})
    for filename, rows in (("targets.jsonl", targets), ("raw_events.jsonl", raw)):
        with (destination / filename).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
    with (destination / "audited_labels.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(labels[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(labels)
    (destination / "transaction.json").write_text(json.dumps(raw[0], indent=2) + "\n")


if __name__ == "__main__":
    generate(Path(__file__).parent / ".runtime" / "synthetic-scam")
