"""Offline tests for data identity, coverage, source semantics, and label admission."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.collection import CollectionError, EtherscanClient, collect_dataset
from packages.data import normalize_bundle, normalize_records
from packages.labeling import SOURCE_ADAPTERS, import_labels, reconcile_labels
from packages.transactions import TRANSFER_TOPIC, V2_TOPICS, decode_v2_log, resolve_transaction

A, B, POOL, FACTORY = ("0x" + digit * 40 for digit in "1234")
TX = "0x" + "a" * 64
BLOCK = "0x" + "b" * 64


def tx(**changes):
    return {"hash": TX, "blockNumber": "1", "blockHash": BLOCK, "timeStamp": "90",
            "from": A, "to": B, "value": "100000000000000000000000000001",
            "isError": "0", "input": "0x", **changes}


def abi_address(value):
    return "0x" + value[2:].rjust(64, "0")


def log(topic=TRANSFER_TOPIC, topics=None, words=(11,), **changes):
    return {"address": POOL, "transactionHash": TX, "blockNumber": "0x1", "blockHash": BLOCK,
            "timeStamp": "0x5a", "logIndex": "0x0", "topics": topics or [topic, abi_address(A), abi_address(B)],
            "data": "0x" + "".join(format(value, "064x") for value in words), **changes}


class NormalizationTests(unittest.TestCase):
    def test_official_bare_hex_zero_log_index(self):
        events, audit = normalize_records([log(logIndex="0x")])
        self.assertTrue(audit["complete"])
        self.assertEqual(events[0]["log_index"], 0)

    def test_integer_precision_failed_calls_and_zero_calls(self):
        events, audit = normalize_records([tx(), tx(hash="0x" + "c" * 64, isError="1"),
                                           tx(hash="0x" + "d" * 64, value="0", input="0x1234")])
        self.assertTrue(audit["complete"])
        money = [event for event in events if event["relation"] == "external_eth"]
        self.assertEqual(len(money), 1)
        self.assertEqual(money[0]["raw_amount"], "100000000000000000000000000001")
        self.assertEqual(money[0]["decimals"], 18)
        self.assertEqual({event["relation"] for event in events}, {"external_eth", "failed_call", "call"})

    def test_root_trace_not_double_counted(self):
        events, audit = normalize_records([tx(), tx(source_kind="internal", traceId="0", type="call")])
        self.assertEqual(len([e for e in events if e["relation"].endswith("_eth")]), 1)
        self.assertEqual(len(audit["suppressed_root_internal"]), 1)

    def test_nested_trace_remains_distinct(self):
        events, audit = normalize_records([tx(), tx(source_kind="internal", traceId="0_1", type="call")])
        self.assertEqual(len([e for e in events if e["relation"].endswith("_eth")]), 2)

    def test_conflicting_duplicates_fail_audit(self):
        _, audit = normalize_records([tx(), tx(value="25")])
        self.assertFalse(audit["complete"])
        self.assertIn("conflicting_duplicate_event", [item["reason"] for item in audit["invalid_records"]])

    def test_conflicting_execution_flags_and_wrong_chain_rejected(self):
        _, audit = normalize_records([tx(isError="0", txreceipt_status="0"), tx(chainId="56")])
        self.assertFalse(audit["complete"])
        self.assertEqual(len(audit["invalid_records"]), 2)

    def test_unknown_success_retained_as_attempt_and_failed_logs_rejected(self):
        unknown = tx()
        unknown.pop("isError")
        events, audit = normalize_records([unknown, log(success=False)])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["relation"], "call")
        self.assertIsNone(events[0]["raw_amount"])
        self.assertEqual(events[0]["attempted_raw_amount"], unknown["value"])
        self.assertIsNone(events[0]["success"])
        self.assertEqual(len(audit["missing_success_events"]), 1)
        self.assertIn("persistent_failed_log", [item["reason"] for item in audit["invalid_records"]])

    def test_raw_api_errors_and_request_chain_are_rejected(self):
        for raw in ({"source_kind": "normal", "response": {"status": "0", "message": "NOTOK", "result": []}},
                    {"request": {"action": "txlist", "chainid": "56"}, "response": {"result": [tx()]}},
                    {"source_kind": "normal", "response": {"error": {"message": "unavailable"}, "result": []}}):
            events, audit = normalize_records([raw])
            self.assertFalse(audit["complete"])
            self.assertEqual(events, [])
        _, audit = normalize_records([{"source_kind": "logs", "response": {
            "status": "0", "message": "No logs found", "result": []}}])
        self.assertTrue(audit["complete"])

    def test_duplicate_known_decimals_or_block_hash_conflict(self):
        token = tx(source_kind="erc20", contractAddress=POOL, tokenDecimal="18", value="11", logIndex="0")
        _, audit = normalize_records([token, {**token, "tokenDecimal": "6"}])
        self.assertFalse(audit["complete"])
        _, audit = normalize_records([tx(), tx(blockHash="0x" + "c" * 64)])
        self.assertFalse(audit["complete"])

    def test_v2_lp_and_unrelated_nft_shape(self):
        events, audit = normalize_records([log()], {POOL: "pool"})
        self.assertEqual(events[0]["relation"], "lp_transfer")
        _, nft_audit = normalize_records([log(topics=[TRANSFER_TOPIC, abi_address(A), abi_address(B), abi_address(A)], words=())])
        self.assertFalse(nft_audit["complete"])
        self.assertTrue(audit["complete"])

    def test_all_v2_logs_decode_expected_fields(self):
        topics = {name: topic for topic, name in V2_TOPICS.items()}
        pair = decode_v2_log(log(topics=[topics["pair_created"], abi_address(A), abi_address(B)],
                                 words=(int(POOL, 16), 1), address=FACTORY))
        self.assertEqual(pair["pool"], POOL)
        self.assertEqual(pair["token0"], A)
        sync = decode_v2_log(log(topics=[topics["sync"]], words=(100, 200)))
        self.assertEqual(sync["reserve1"], "200")
        mint = decode_v2_log(log(topics=[topics["mint"], abi_address(A)], words=(10, 20)))
        self.assertEqual(mint["dst"], POOL)
        burn = decode_v2_log(log(topics=[topics["burn"], abi_address(A), abi_address(B)], words=(10, 20)))
        self.assertEqual(burn["src"], POOL)
        swap = decode_v2_log(log(topics=[topics["swap"], abi_address(A), abi_address(B)], words=(10, 0, 0, 20)))
        self.assertEqual(swap["amount1_out"], "20")

    def test_missing_log_identity_is_rejected_then_receipt_hydrates(self):
        token = tx(source_kind="erc20", contractAddress=POOL, tokenDecimal="18", value="11")
        _, audit = normalize_records([token])
        self.assertFalse(audit["complete"])
        events, audit = normalize_records([token, log()])
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["hydrated_erc20_history"], 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["decimals"], 18)
        self.assertEqual(len(events[0]["lineage"]["token_metadata_sources"]), 1)

    def test_token_metadata_conflict_and_noncanonical_abi_address(self):
        token = tx(source_kind="erc20", contractAddress=POOL, tokenDecimal="18", value="11")
        _, audit = normalize_records([token, {**token, "tokenDecimal": "6"}, log()])
        self.assertFalse(audit["complete"])
        self.assertIn("conflicting_token_decimals_metadata", [item["reason"] for item in audit["invalid_records"]])
        _, audit = normalize_records([log(topics=[TRANSFER_TOPIC, "0x" + "f" * 24 + A[2:], abi_address(B)])])
        self.assertFalse(audit["complete"])

    def test_receipt_context_and_removed_logs(self):
        receipt_log = log()
        receipt_log.pop("timeStamp")
        events, audit = normalize_records([{"source_kind": "receipt", "timestamp": 90,
                                            "response": {"result": {"status": "0x1", "logs": [receipt_log]}}}])
        self.assertTrue(audit["complete"])
        self.assertEqual(events[0]["timestamp"], 90)
        _, audit = normalize_records([log(removed=True)])
        self.assertFalse(audit["complete"])

    def test_resolver_does_not_propagate_labels(self):
        participants = resolve_transaction(tx(), {"logs": [log()]}, {A: {"label": "phishing"}})
        self.assertTrue(all(item["label_inherited"] is False for item in participants))
        self.assertIsNone(next(item for item in participants if item["address"] == B)["known_entity"])


class SourceAndLabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def csv(self, name, value):
        path = self.root / name
        path.write_text(value)
        return path

    def test_ponzi_zip_error_and_conflict(self):
        path = self.root / "labels.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Smart Ponzi Scheme Labels/Ponzi_label.csv", f"Contract,Ponzi\n{A},0\n{B},error\n")
        records = import_labels("xblock_ponzi", path, "ponzi")
        self.assertEqual(records[0]["label_status"], "temporally_unresolved")
        self.assertEqual(records[1]["label_status"], "invalid")
        unica = import_labels("unica", self.csv("unica.csv", f"{A},Scheme\n{A.upper().replace('0X','0x')},Scheme\n"), "ponzi")
        labels = reconcile_labels(records + unica, [{"sample_id": "a", "task_id": "ponzi", "target": A, "cutoff": 100}])
        self.assertEqual(labels[0]["label_status"], "disputed")
        self.assertFalse(labels[0]["eligible"])

    def test_forta_and_source_zero_not_reviewed_benign(self):
        forta = import_labels("forta", self.csv("forta.csv", f"address,etherscan_labels,etherscan_tag,is_contract\n{A},phish-hack,Fake_Phishing1,False\n"), "phishing")
        self.assertEqual(forta[0]["mapped_label"], 1)
        self.assertEqual(forta[0]["role"], "unknown")
        background = import_labels("xblock_phishing", self.csv("phish.csv", f"address,isp\n{B},0\n"), "phishing")
        self.assertEqual(background[0]["label_status"], "unlabeled")
        self.assertIsNone(background[0]["mapped_label"])

    def test_tokenscout_mapping_and_weak_evidence(self):
        mapping = self.root / "mapping.json"
        mapping.write_text(json.dumps({A: 7, B: 8}))
        path = self.csv("tokens.csv", "tokens,t1-labels,t2-labels\n7,scam,rugpull\n8,truthworthy,truthworthy\n")
        records = import_labels("tokenscout", path, "rug_pull", mapping)
        self.assertEqual(records[0]["entity_id"], A)
        self.assertEqual(records[0]["evidence_strength"], "weak_source_label")
        self.assertIsNone(records[1]["mapped_label"])
        self.assertEqual(import_labels("tokenscout", path, "rug_pull")[0]["label_status"], "invalid")

    def test_audited_label_admission_and_training_availability(self):
        path = self.csv("audit.csv", "task_id,entity_id,mapped_label,label_status,role,valid_from,valid_to,label_available_at,evidence_ref,audit_decision\n"
                        f"ponzi,{A},1,supported_positive,target_contract,10,100,80,report,admitted\n")
        records = import_labels("audited", path, "ponzi")
        target = {"sample_id": "a", "task_id": "ponzi", "target": A, "cutoff": 90}
        admitted = reconcile_labels(records, [target], training_as_of=85)[0]
        self.assertTrue(admitted["eligible"])
        self.assertEqual(admitted["observed_target"], 1)
        self.assertFalse(reconcile_labels(records, [target], training_as_of=79)[0]["eligible"])
        self.assertFalse(reconcile_labels(records, [{**target, "cutoff": 110}])[0]["eligible"])
        records[0]["role"] = "unknown"
        self.assertEqual(reconcile_labels(records, [target])[0]["label_status"], "temporally_unresolved")

    def test_positive_phishing_cannot_have_benign_role(self):
        path = self.csv("role.csv", "entity_id,mapped_label,label_status,role,valid_from,audit_decision\n"
                        f"{A},1,supported_positive,benign_address,0,admitted\n")
        records = import_labels("audited", path, "phishing")
        row = reconcile_labels(records, [{"sample_id": "x", "task_id": "phishing", "target": A, "cutoff": 90}])[0]
        self.assertFalse(row["eligible"])
        self.assertEqual(row["reason"], "role_incompatible_with_positive_label")

    def test_unlabeled_not_supervised_but_background_metadata_retained(self):
        target = {"sample_id": "b", "task_id": "phishing", "target": B, "cutoff": 90,
                  "background_selected": True, "cohort_id": "frozen"}
        record = reconcile_labels([], [target])[0]
        self.assertFalse(record["eligible"])
        self.assertTrue(record["data_eligible"])
        self.assertEqual(record["reason"], "unlabeled")
        self.assertTrue(record["background_selected"])
        self.assertFalse(reconcile_labels([], [{**target, "coverage": {"complete": False}}])[0]["data_eligible"])

    def test_verified_campaign_metadata_survives_labeling(self):
        target = {"sample_id": "campaign", "task_id": "ponzi", "target": A,
                  "cutoff": 90, "chain_id": 1, "group_id": "campaign-a",
                  "group_verified": True, "group_evidence_ref": "reviewed-report"}
        row = reconcile_labels([], [target])[0]
        for key in ("chain_id", "group_id", "group_verified", "group_evidence_ref"):
            self.assertEqual(row[key], target[key])

    def test_crp_xlsx_preserves_mechanism_candidates(self):
        path = self.root / "crp.xlsx"
        xml = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
               '<row r="1"><c r="A1" t="inlineStr"><is><t>Pattern</t></is></c><c r="B1" t="inlineStr"><is><t>Address</t></is></c></row>'
               f'<row r="2"><c r="A2" t="inlineStr"><is><t>Withdrawing Liquidity</t></is></c><c r="B2" t="inlineStr"><is><t>{A}</t></is></c></row>'
               '</sheetData></worksheet>')
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml", xml)
        record = import_labels("crpwarner", path, "rug_pull")[0]
        self.assertEqual(record["mapped_label"], 1)
        self.assertEqual(record["label_status"], "temporally_unresolved")
        self.assertEqual(record["evidence_strength"], "report_candidate")
        self.assertTrue({"forta", "tokenscout", "crpwarner"}.issubset(SOURCE_ADAPTERS))


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_paginated_history_resumes_without_transport(self):
        rows = [tx(hash="0x" + str(i) * 64) for i in (1, 2, 3)]
        first = EtherscanClient(self.root, {"fixtures": {"txlist": rows}, "page_size": 2})
        actual, coverage = first.history("txlist", A, 1, 2)
        self.assertTrue(coverage["complete"])
        self.assertEqual(len(actual), 3)
        def forbidden(query):
            raise AssertionError("cache resume made a new request")
        second = EtherscanClient(self.root, {"page_size": 2}, forbidden)
        _, coverage = second.history("txlist", A, 1, 2)
        self.assertTrue(coverage["complete"])
        self.assertEqual(second.request_count, 0)
        self.assertEqual(second.cached_count, 2)

    def test_split_exhausted_range_and_single_block_gap(self):
        rows = [tx(blockNumber=str(i), hash="0x" + str(i) * 64) for i in (1, 2)]
        def transport(query):
            picked = [row for row in rows if query["startblock"] <= int(row["blockNumber"]) <= query["endblock"]]
            return {"status": "1", "message": "OK", "result": picked}
        client = EtherscanClient(self.root, {"page_size": 2, "max_pages": 1}, transport)
        actual, coverage = client.history("txlist", A, 1, 2)
        self.assertTrue(coverage["complete"])
        self.assertEqual(len(actual), 2)
        saturated = EtherscanClient(self.root / "saturated", {"fixtures": {"txlist": [{**row, "blockNumber": "1"} for row in rows]}, "page_size": 2, "max_pages": 1})
        _, coverage = saturated.history("txlist", A, 1, 1)
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["gaps"][0]["reason"], "page_limit_reached")

    def test_history_rejects_nonobject_or_out_of_range_response(self):
        for index, rows in enumerate(([tx(blockNumber="99")], ["bad-row"])):
            client = EtherscanClient(self.root / str(index), {"fixtures": {"txlist": rows}})
            actual, coverage = client.history("txlist", A, 1, 2)
            self.assertFalse(coverage["complete"])
            self.assertEqual(actual, [])

    def test_retry_and_error_not_treated_as_empty_history(self):
        calls = []
        def transport(query):
            calls.append(query)
            return {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"} if len(calls) == 1 else {"status": "1", "result": []}
        client = EtherscanClient(self.root, {"retries": 1, "api_key": "secret-key"}, transport)
        _, coverage = client.history("txlist", A, 1, 2)
        self.assertTrue(coverage["complete"])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("secret-key", next((self.root / "raw_requests").glob("*.json")).read_text())
        bad = EtherscanClient(self.root / "bad", {"fixtures": {"txlist": {"status": "0", "message": "NOTOK", "result": "Invalid API Key"}}})
        _, coverage = bad.history("txlist", A, 1, 2)
        self.assertFalse(coverage["complete"])

    def test_network_disabled_and_page_cap(self):
        client = EtherscanClient(self.root, {"page_size": 10000, "rate_limit_rps": 10})
        self.assertEqual(client.page_size, 1000)
        self.assertEqual(client.rate, 3)
        with self.assertRaisesRegex(CollectionError, "network_disabled"):
            client.request("account", "txlist", address=A)

    def test_collect_and_normalize_raw_bundle(self):
        target = {"sample_id": "a", "task_id": "phishing", "target": A, "cutoff": 100,
                  "observation_start": 0, "start_block": 1, "end_block": 2}
        manifest = collect_dataset([target], self.root, {"fixtures": {"txlist": [tx()], "txlistinternal": []}})
        self.assertTrue(manifest["complete"])
        events, audit = normalize_bundle(self.root)
        self.assertTrue(audit["complete"])
        self.assertEqual(len(events), 1)
        self.assertTrue((self.root / "targets_with_coverage.jsonl").exists())
        before = sorted(self.root.rglob("*"))
        collect_dataset([target], self.root, {}, dry_run=True)
        self.assertEqual(before, sorted(self.root.rglob("*")))

    def test_receipt_hydration_preserves_token_precision_in_collection(self):
        token = tx(source_kind="erc20", contractAddress=POOL, tokenDecimal="18", value="11")
        def transport(query):
            if query["action"] == "tokentx":
                return {"status": "1", "result": [token]}
            return {"result": {"status": "0x1", "logs": [log()]}}
        target = {"sample_id": "token", "task_id": "phishing", "target": A,
                  "cutoff": 100, "observation_start": 0, "start_block": 1, "end_block": 2}
        manifest = collect_dataset([target], self.root, {"transport": transport, "actions": ["tokentx"], "hops": 1})
        self.assertTrue(manifest["complete"])
        collected = [json.loads(line) for line in (self.root / "events.jsonl").read_text().splitlines()]
        events, audit = normalize_bundle(self.root)
        self.assertTrue(audit["complete"])
        self.assertEqual(collected[0]["decimals"], 18)
        self.assertEqual(events[0]["decimals"], 18)

    def test_explicit_pool_mapping_and_custom_window_are_preserved(self):
        cutoff = 1_000_000
        target = {"sample_id": "rug", "task_id": "rug_pull", "target": A,
                  "cutoff": cutoff, "pools": [POOL], "start_block": 1, "end_block": 2}
        from packages.token import UNISWAP_V2_FACTORY
        target.update(token_metadata={"decimals": 18, "verified_at_block": 2, "evidence_ref": "synthetic://token"},
                      pool_metadata=[{"pool": POOL, "token0": A, "token1": B, "factory": UNISWAP_V2_FACTORY,
                                      "verified_at_block": 2, "evidence_ref": "synthetic://pool"}])
        manifest = collect_dataset([target], self.root, {"fixtures": {"getLogs": [log(timeStamp=str(cutoff - 1))], "txlist": [], "txlistinternal": []}, "window_days": 7})
        self.assertTrue(manifest["complete"])
        self.assertEqual(manifest["coverage"][0]["observation_start"], cutoff - 7 * 86400)
        events, audit = normalize_bundle(self.root)
        self.assertTrue(audit["complete"])
        self.assertEqual(events[0]["relation"], "lp_transfer")

    def test_bfs_requests_frontier_but_not_last_hop_boundary(self):
        third = "0x" + "5" * 40
        records = [tx(value="10"), tx(hash="0x" + "e" * 64, **{"from": B, "to": third, "value": "20"})]
        requested = []
        def transport(query):
            requested.append(query["address"])
            result = [row for row in records if query["address"] in (row["from"], row["to"])] if query["action"] == "txlist" else []
            return {"status": "1", "result": result}
        target = {"sample_id": "bfs", "task_id": "phishing", "target": A, "cutoff": 100,
                  "observation_start": 0, "start_block": 1, "end_block": 2}
        manifest = collect_dataset([target], self.root, {"transport": transport, "graph": {"hops": 2, "fanouts": [2, 2], "max_nodes": 3}})
        self.assertTrue(manifest["complete"])
        self.assertEqual(set(requested), {A, B})
        self.assertNotIn(third, requested)
        self.assertTrue(manifest["coverage"][0]["neighborhood_history_complete"])
        self.assertEqual(manifest["coverage"][0]["sampled_node_count"], 3)

    def test_fixture_directory_and_incomplete_bundle(self):
        fixtures = self.root / "fixtures"
        fixtures.mkdir()
        (fixtures / "txlist.json").write_text(json.dumps({"status": "1", "result": []}))
        (fixtures / "txlistinternal.json").write_text(json.dumps({"status": "0", "result": "Invalid API Key", "message": "NOTOK"}))
        target = {"sample_id": "bad", "task_id": "phishing", "target": A, "cutoff": 100,
                  "observation_start": 0, "start_block": 1, "end_block": 2}
        output = self.root / "output"
        manifest = collect_dataset([target], output, {"fixture_dir": str(fixtures)})
        self.assertFalse(manifest["complete"])
        _, audit = normalize_bundle(output)
        self.assertFalse(audit["complete"])
        self.assertTrue(audit["collection_incomplete"])


if __name__ == "__main__":
    unittest.main()
