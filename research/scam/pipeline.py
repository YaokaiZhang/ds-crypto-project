"""Run any Scam task through sources, collect, prepare and train."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import argparse
import io
import json
from pathlib import Path
import sys
import time
import uuid

from packages.collection import transient_network_error
from packages.io import load_json, save_json, sha256_file
from ._commands import main as scam_main
from .storage import checked_name, dataset_path, model_path

STAGES = ("sources", "collect", "prepare", "train")
TOKEN_TASKS = {"honeypot", "rug_pull"}
TRAINING_OPTIONS = ("epochs", "patience", "min_delta", "device", "architecture", "loss")


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, text):
        self.console.write(text)
        self.log.write(text)
        self.log.flush()
        return len(text)

    def flush(self):
        self.console.flush()
        self.log.flush()

    def isatty(self):
        return self.console.isatty()

    def fileno(self):
        return self.console.fileno()

    @property
    def progress_stream(self):
        return getattr(self.console, "progress_stream", self.console)


def retryable(code, result, errors):
    if code == 3:
        coverage = result.get("collection", {}).get("coverage", [])
        terminal = ("checksum_mismatch", "invalid_cached_request", "invalid api key", "invalid api-key",
                    "missing_fixture", "cached_provider_mismatch", "recent_normalization_failed", "recent_receipt_", "recent_trace_",
                    "recent_row_outside", "response_byte_budget_exhausted", "sample_byte_budget_exhausted")
        if result.get("resume", "").startswith("row budget reached"):
            return False
        failures = [json.dumps(row).lower() for row in coverage]
        if any(marker in failure for failure in failures for marker in ("invalid api key", "invalid api-key", "missing_etherscan")):
            return False
        return not coverage or any(not row.get("normalization_failure")
                    and ("recent_receipt_verification_budget_pending" in failure
                         or not any(marker in failure for marker in terminal))
                    for row, failure in zip(coverage, failures))
    return code == 2 and (transient_network_error(errors) or any(marker in errors for marker in (
        "public_label_download_failed", "historical_rpc_request_failed",
        "snapshot_is_running_in_another_process")))


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--task", choices=["phishing", "ponzi", "honeypot", "rug_pull"], default="phishing")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--output", help="Override dataset directory")
    p.add_argument("--stage", choices=[*STAGES, "all", "status"], default="all",
                   help="all runs sources -> collect (including graphs) -> prepare -> train")
    p.add_argument("--settings")
    p.add_argument("--config")
    p.add_argument("--profile", choices=["recent", "full-history"])
    p.add_argument("--source-snapshot")
    p.add_argument("--background-snapshot")
    p.add_argument("--source-as-of", type=int)
    p.add_argument("--per-class", type=int)
    p.add_argument("--negative-count", type=int)
    p.add_argument("--positive-count", type=int)
    p.add_argument("--candidate-count", type=int)
    p.add_argument("--graph-run", help="Token graph version; defaults to recent-v1")
    p.add_argument("--graph-cohort", choices=["contemporary", "historical", "both"])
    p.add_argument("--historical-cutoff")
    p.add_argument("--graph-limit", type=int)
    p.add_argument("--strict-collection", action="store_true")
    p.add_argument("--xblock-cutoff")
    p.add_argument("--unica-cutoff")
    p.add_argument("--background-blocks", type=int, default=384)
    p.add_argument("--discover-background", action="store_true")
    p.add_argument("--allow-network", action="store_true")
    p.add_argument("--drop-failed", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="Plan/validate without writes, network or fitting")
    p.add_argument("--progress", choices=["auto", "on", "off"], default="auto")
    p.add_argument("--max-attempts", type=int, default=20)
    p.add_argument("--retry-delay", type=float, default=30)
    p.add_argument("--run", help="Required for all/train; immutable model run name")
    p.add_argument("--patience", type=int)
    p.add_argument("--min-delta", type=float)
    p.add_argument("--epochs", type=int)
    p.add_argument("--device", choices=["cpu", "mps", "cuda", "auto"])
    p.add_argument("--architecture", choices=["mean_sage", "directed_edge_sage"])
    p.add_argument("--loss", choices=["weighted_bce", "focal"])
    return p


def validate_options(a):
    checked_name(a.snapshot)
    if a.run:
        checked_name(a.run)
    if a.max_attempts < 1 or a.retry_delay < 0:
        raise ValueError("attempts must be positive and retry delay nonnegative")
    if a.stage in {"all", "train"} and not a.run:
        raise ValueError("--stage all/train requires --run NAME; use individual data stages to stop before training")
    if a.stage not in {"all", "train"} and any(getattr(a, name) is not None for name in TRAINING_OPTIONS):
        raise ValueError("training_options_require_stage_all_or_train")
    if a.run and a.stage not in {"all", "train", "status"}:
        raise ValueError("run_requires_stage_all_train_or_status")
    task_options = {
        "phishing": ("profile", "background_snapshot", "source_as_of", "per_class", "discover_background"),
        "ponzi": ("xblock_cutoff", "unica_cutoff"),
        "honeypot": ("candidate_count", "graph_cohort"),
        "rug_pull": ("positive_count",),
    }
    for task, names in task_options.items():
        if a.task != task and any(getattr(a, name) not in (None, False) for name in names):
            raise ValueError(f"{task}_options_require_task_{task}")
    if a.task not in {"ponzi", "rug_pull"} and a.negative_count is not None:
        raise ValueError("negative_count_requires_ponzi_or_rug_pull")
    if a.task in TOKEN_TASKS:
        if a.config or a.source_snapshot or a.drop_failed:
            raise ValueError("token_tasks_use_settings_generated_configs_and_strict_collection")
        if a.task == "rug_pull" and a.stage not in {"sources", "all"} and any(
                value is not None for value in (a.positive_count, a.negative_count, a.historical_cutoff)):
            raise ValueError("rug_pull_collection_uses_frozen_verified_cohort_and_cutoff")
        if a.stage not in {"all", "collect"} and (a.graph_limit is not None or a.strict_collection):
            raise ValueError("graph_limit_and_strict_collection_require_stage_all_or_collect")
        a.graph_run = checked_name(a.graph_run or "recent-v1")
    elif a.graph_run or a.graph_cohort or a.historical_cutoff or a.graph_limit is not None or a.strict_collection:
        raise ValueError("graph_options_require_a_token_task")
    if a.settings:
        if not isinstance(load_json(a.settings), dict):
            raise ValueError("settings must be a JSON object")
    if a.config and not isinstance(load_json(a.config), dict):
        raise ValueError("config must be a JSON object")


def prepared_path(a, out):
    if a.task in TOKEN_TASKS:
        return out / "graph_runs" / a.graph_run / "prepared"
    return out / "prepared"


def data_command(a, out, stage):
    token = a.task in TOKEN_TASKS
    internal = ({"sources": "all", "collect": "graphs", "prepare": "prepare-training"} if token else
                {"sources": "cohort", "collect": "collect", "prepare": "prepare"})[stage]
    command = ["prepare-" + a.task.replace("_", "-"), "--task", a.task, "--snapshot", a.snapshot,
               "--output", str(out), "--stage", internal, "--progress", a.progress]
    flags = ["settings"]
    if token:
        flags += ["graph_run"]
        if a.task == "honeypot" and stage == "sources":
            flags += ["candidate_count"]
        if stage == "collect":
            flags += ["graph_limit"]
            if a.task == "honeypot":
                flags += ["graph_cohort", "historical_cutoff"]
            if a.strict_collection:
                command.append("--strict-collection")
        if a.task == "rug_pull" and stage == "sources":
            flags += ["positive_count", "negative_count", "historical_cutoff"]
    else:
        flags += ["config", "source_snapshot"]
        if a.task == "phishing":
            flags += ["profile", "background_snapshot", "source_as_of", "per_class"]
            if stage == "sources" and a.discover_background:
                command += ["--discover-background", "--background-blocks", str(a.background_blocks)]
        else:
            flags += ["negative_count", "xblock_cutoff", "unica_cutoff"]
        if stage == "prepare" and a.drop_failed:
            command.append("--drop-failed")
    for name in flags:
        value = getattr(a, name)
        if value is not None:
            command += ["--" + name.replace("_", "-"), str(value)]
    if a.allow_network:
        command.append("--allow-network")
    if a.dry_run:
        command.append("--dry-run")
    return command


def invoke(command, out, stage, attempt, dry_run):
    stdout, stderr = io.StringIO(), io.StringIO()
    if dry_run:
        with redirect_stdout(stdout), redirect_stderr(Tee(sys.stderr, stderr)):
            code = scam_main(command)
    else:
        logs = out / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        with (logs / f"{stamp}-{stage}-{attempt}.log").open("w") as log:
            with redirect_stdout(stdout), redirect_stderr(Tee(Tee(sys.stderr, log), stderr)):
                code = scam_main(command)
        (logs / f"{stamp}-{stage}-{attempt}.json").write_text(stdout.getvalue() or "{}\n")
    result = json.loads(stdout.getvalue()) if stdout.getvalue().strip() else {}
    return code, result, stderr.getvalue()


def run_data_stage(a, out, stage):
    command = data_command(a, out, stage)
    for attempt in range(1, a.max_attempts + 1):
        code, result, errors = invoke(command, out, stage, attempt, a.dry_run)
        print(json.dumps({"stage": stage, "attempt": attempt, "exit_code": code,
                          "status": result.get("status", "error"), "dataset": str(out),
                          **({"plan": result} if a.dry_run else {})}), flush=True)
        if not code:
            return 0
        if a.dry_run or attempt == a.max_attempts or not retryable(code, result, errors):
            if code == 3 and a.drop_failed and a.stage == "all" and stage == "collect":
                print("[collect] retry budget ended; prepare will audit recorded sample exclusions", file=sys.stderr)
                return 0
            return code
        print(f"[{stage}] retry in {a.retry_delay:g}s; completed samples retained", file=sys.stderr, flush=True)
        time.sleep(a.retry_delay)
    return 0


def train(a, out, *, verify=True):
    prepared = prepared_path(a, out)
    if verify:
        code, _, _ = invoke(data_command(a, out, "prepare"), out, "verify-training", 1, a.dry_run)
        if code:
            return code
    destination = model_path(a.task, a.snapshot, a.run)
    command = ["train", "--task", a.task, "--config", str(prepared / "training_config.json"),
               "--graphs", str(prepared / "graphs.jsonl"), "--supervision", str(prepared / "supervision.jsonl"),
               "--splits", str(prepared / "splits.jsonl"), "--output", str(destination), "--progress", a.progress]
    overrides = {name: getattr(a, name) for name in TRAINING_OPTIONS if getattr(a, name) is not None}
    for name, value in overrides.items():
        command += ["--" + name.replace("_", "-"), str(value)]
    if a.dry_run:
        command.append("--dry-run")
    code = scam_main(command)
    if code == 0 and not a.dry_run:
        save_json(destination / "run_manifest.json", {"task_id": a.task, "snapshot": a.snapshot,
            **({"graph_run": a.graph_run} if a.task in TOKEN_TASKS else {}),
            "run": a.run, "dataset": str(prepared),
            "dataset_manifest_sha256": sha256_file(prepared / "dataset_manifest.json"),
            "training_config_sha256": sha256_file(prepared / "training_config.json"),
            "training_overrides": overrides,
            "training_summary_sha256": sha256_file(destination / "training_summary.json"),
            "bundle_manifest_sha256": sha256_file(destination / "bundle/manifest.json")})
    return code


def dry_run_all(a, out):
    # Later stages of a new snapshot depend on outputs which a dry run must not create.
    # Existing prepared datasets additionally get the real admission/hash validation.
    report = {"status": "planned", "task_id": a.task, "stages": list(STAGES),
              "output": str(out), "model_output": str(model_path(a.task, a.snapshot, a.run)),
              "network_performed": False, "training_started": False,
              "commands": {stage: data_command(a, out, stage) for stage in STAGES[:-1]},
              "training_validation": "deferred_until_prepared_inputs_exist"}
    if (prepared_path(a, out) / "dataset_manifest.json").exists():
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = train(a, out)
        if code:
            return code
        report["training_validation"] = "validated"
    print(json.dumps(report, indent=2))
    return 0


def status(a, out):
    report = {"task_id": a.task, "snapshot": a.snapshot, "stages": list(STAGES),
              "dataset": str(out), "prepared": (prepared_path(a, out) / "dataset_manifest.json").exists(),
              "data_status": load_json(out / "status.json") if (out / "status.json").exists() else {"status": "not_started"}}
    if a.task in TOKEN_TASKS:
        report["graph_run"] = a.graph_run
        root = prepared_path(a, out).parent
        for name in ("progress", "graph_manifest"):
            if (root / f"{name}.json").exists():
                report["graph_" + name] = load_json(root / f"{name}.json")
    parent = model_path(a.task, a.snapshot, a.run or "unused").parent
    runs = [parent / a.run] if a.run else sorted(parent.glob("*"))
    report["model_runs"] = {p.name: load_json(p / "training_summary.json").get("status")
                            for p in runs if (p / "training_summary.json").exists()}
    print(json.dumps(report, indent=2))
    return 0


def run(argv=None):
    a = parser().parse_args(argv)
    validate_options(a)
    out = Path(a.output).resolve() if a.output else dataset_path(a.task, a.snapshot)
    if a.stage == "status":
        return status(a, out)
    if a.stage in {"all", "train"} and not a.dry_run:
        destination = model_path(a.task, a.snapshot, a.run)
        if destination.exists() and any(destination.iterdir()):
            raise ValueError("model_run_exists_use_a_new_run_name")
    if a.stage == "all" and a.dry_run:
        return dry_run_all(a, out)
    stages = STAGES if a.stage == "all" else (a.stage,)
    for stage in stages:
        code = train(a, out, verify=a.stage != "all") if stage == "train" else run_data_stage(a, out, stage)
        if code:
            return code
    return 0


def main(argv=None):
    try:
        return run(argv)
    except SystemExit as error:
        return error.code
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "error", "reason": str(error)}), file=sys.stderr)
        return 2
