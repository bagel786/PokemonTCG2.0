#!/usr/bin/env python3
"""Run 5k+ fast screens, untouched confirmation, packaging, and gated upload."""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_recovery_probes import build_unshielded, safe_extract
from scripts.package_order_ppo_candidate import build as build_final_package
from scripts.run_azure_order_ppo import (
    KEY, RATE_PER_WORKER_HOUR, REMOTE, SPEND_CAP_USD, WORKERS,
    deallocate, prepare, run, scp_from, scp_to, ssh, start,
)
from training.order_promotion import confirmation_gate, direct_gate, fast_screen, select_checkpoints, wilson_lower

OUTPUT = ROOT / "artifacts" / "order_ppo" / "evaluation"
DEVELOPMENT = {
    "owned_d842": "artifacts/recovery_final/opponents/d842",
    "owned_r0": "artifacts/recovery_r0_package/extracted/r0_play_binding",
    "owned_a2": "artifacts/recovery_probes/extracted/a2",
    "owned_master_v1": "artifacts/recovery_final/opponents/master_v1",
    "authentic_alakazam_2_4a": "freshstart/elite_submissions/alakazam_2_4a",
    "curriculum_lucario": "artifacts/recovery_final/opponents/lucario",
    "curriculum_crustle": "artifacts/recovery_final/opponents/crustle",
    "curriculum_ogerpon": "artifacts/recovery_final/opponents/ogerpon",
    "curriculum_bellibolt": "artifacts/recovery_final/opponents/bellibolt",
    "curriculum_starmie_froslass": "artifacts/recovery_final/opponents/starmie_froslass",
}
HOLDOUTS = {
    "replay_refresh": "artifacts/recovery_final/opponents/replay_refresh",
    "v2_2": "artifacts/recovery_final/opponents/v2_2",
    "alakazam_2_7": "freshstart/elite_submissions/alakazam_2_7",
}
SAFETY = {name: f"artifacts/recovery_final/opponents/{name}" for name in
          ("lucario", "crustle", "ogerpon", "bellibolt", "starmie_froslass")}
CONTROL = "artifacts/recovery_final/opponents/d842"


def reset_directory(path: Path) -> None:
    resolved = path.resolve()
    root = OUTPUT.resolve()
    if root != resolved and root not in resolved.parents:
        raise RuntimeError(f"refusing reset outside evaluation root: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def candidate_stages() -> dict[str, str]:
    result = {}
    package_root = OUTPUT / "fast_packages"
    package_root.mkdir(parents=True, exist_ok=True)
    for name in ("first", "second_a", "second_b"):
        model = ROOT / "artifacts" / "order_ppo" / "azure" / "checkpoints" / name / "policy_weights.npz"
        if not model.exists():
            raise FileNotFoundError(model)
        package = build_unshielded(f"order_{name}", model, package_root)
        stage = OUTPUT / "candidates" / name
        reset_directory(stage)
        safe_extract(Path(package["archive"]), stage)
        result[name] = stage.relative_to(ROOT).as_posix()
    return result


def build_bundle(candidate_paths: dict[str, str]) -> tuple[Path, str]:
    paths = [
        "training/__init__.py", "training/evaluate_forced_order.py", "training/evaluation_schema.py",
        "ptcg_ai", "vendor/cg", CONTROL, *DEVELOPMENT.values(), *HOLDOUTS.values(), *SAFETY.values(),
        *candidate_paths.values(),
    ]
    files = []
    for relative in paths:
        source = ROOT / relative
        files.extend([source] if source.is_file() else [item for item in source.rglob("*") if item.is_file()])
    bundle = OUTPUT / "evaluation_bundle.tar.gz"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with bundle.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for item in sorted(set(files)):
                    if "__pycache__" in item.parts or item.suffix == ".pyc":
                        continue
                    info = archive.gettarinfo(str(item), arcname=item.relative_to(ROOT).as_posix())
                    info.mtime = 0; info.uid = 0; info.gid = 0; info.uname = ""; info.gname = ""
                    with item.open("rb") as handle:
                        archive.addfile(info, handle)
    return bundle, hashlib.sha256(bundle.read_bytes()).hexdigest()


def budget_check(started: float, prior_spend: float, allowance_hours: float = 0.0) -> None:
    projected = prior_spend + ((time.time() - started) / 3600 + allowance_hours) * len(WORKERS) * RATE_PER_WORKER_HOUR
    if projected >= SPEND_CAP_USD:
        raise RuntimeError(f"combined projected spend ${projected:.2f} reaches ${SPEND_CAP_USD:.2f} cap")


def evaluate(worker: dict, task: dict, started: float, prior_spend: float) -> dict:
    is_authentic_alakazam = "alakazam_2_" in task["opponent"]
    if is_authentic_alakazam and int(task["games"]) >= 1000:
        allowance_hours = 3.0
    elif is_authentic_alakazam:
        allowance_hours = 2.0
    else:
        allowance_hours = 1.0
    budget_check(started, prior_spend, allowance_hours=allowance_hours)
    local = OUTPUT / "results" / task["phase"] / f"{task['label']}.json"
    if local.exists():
        cached = json.loads(local.read_text(encoding="utf-8"))
        cache_valid = (
            int(cached.get("games", -1)) == int(task["games"])
            and int(cached.get("seed", -1)) == int(task["seed"])
            and cached.get("actual_order") == task["order"]
            and cached.get("actual_order_accounting_complete") is True
        )
        if not cache_valid:
            raise RuntimeError(f"invalid cached evaluation result: {local}")
        return {"task": task, "result": cached, "path": str(local), "cached": True}
    remote_output = f"/tmp/{task['label']}.json"
    remote_log = f"/tmp/{task['label']}.log"
    remote_status = f"/tmp/{task['label']}.status"
    remote_pid = f"/tmp/{task['label']}.pid"
    workload = (
        f"cd {REMOTE} && export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 && "
        f"timeout 7200s $HOME/ptcg-venv/bin/python -m training.evaluate_forced_order "
        f"--hero {task['hero']} --opponent {task['opponent']} --actual-order {task['order']} "
        f"--games {task['games']} --workers 8 --seed {task['seed']} --output {remote_output} "
        f"> {remote_log} 2>&1"
    )
    command = (
        f"rm -f {remote_output} {remote_status} {remote_pid} {remote_log}; "
        f"nohup bash -c '{workload}; code=$?; printf \"%s\\n\" \"$code\" > {remote_status}' "
        f">/dev/null 2>&1 </dev/null & echo $! > {remote_pid}"
    )
    try:
        ssh(worker, command, timeout=60)
        deadline = time.time() + 7500
        disconnected_since = None
        while time.time() < deadline:
            try:
                probe = ssh(worker, (
                    f"if test -f {remote_status}; then printf 'status:'; cat {remote_status}; "
                    f"elif test -f {remote_pid} && kill -0 $(cat {remote_pid}) 2>/dev/null; "
                    "then echo running; else echo missing; fi"
                ), timeout=45).stdout.strip()
                disconnected_since = None
            except Exception:
                disconnected_since = disconnected_since or time.time()
                if time.time() - disconnected_since >= 600:
                    raise RuntimeError(f"worker unreachable for 600 seconds: {worker['name']}")
                time.sleep(15)
                continue
            if probe == "running":
                time.sleep(30)
                continue
            if probe.startswith("status:"):
                code = int(probe.split(":", 1)[1].strip())
                if code:
                    raise RuntimeError(f"remote evaluation exited {code}: {task['label']}")
                break
            raise RuntimeError(f"remote evaluation disappeared: {task['label']}: {probe!r}")
        else:
            raise TimeoutError(f"evaluation status deadline exceeded: {task['label']}")
    except Exception:
        try:
            scp_from(worker, remote_log, OUTPUT / "logs" / f"{task['label']}.log")
        except Exception:
            pass
        raise
    last_error = None
    for _ in range(5):
        try:
            scp_from(worker, remote_output, local)
            break
        except Exception as exc:
            last_error = exc
            time.sleep(10)
    else:
        raise RuntimeError(f"could not download completed evaluation {task['label']}: {last_error}")
    return {"task": task, "result": json.loads(local.read_text(encoding="utf-8")), "path": str(local)}


def run_queue(tasks: list[dict], started: float, prior_spend: float) -> list[dict]:
    queue = iter(tasks)
    lock = __import__("threading").Lock()
    def loop(worker):
        rows = []
        while True:
            with lock:
                try: task = next(queue)
                except StopIteration: break
            rows.append(evaluate(worker, task, started, prior_spend))
        return rows
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for rows in pool.map(loop, WORKERS):
            results.extend(rows)
    return results


def merged(cells: list[dict]) -> dict:
    games = sum(int(cell["games"]) for cell in cells)
    wins = sum(int(cell["wins"]) for cell in cells)
    return {
        "games": games, "wins": wins, "win_rate": wins / games,
        "hero_policy_errors": sum(int(cell.get("hero_policy_errors", 0)) for cell in cells),
        "opponent_policy_errors": sum(int(cell.get("opponent_policy_errors", 0)) for cell in cells),
        "actual_order_accounting_complete": all(cell.get("actual_order_accounting_complete") for cell in cells),
        "one_sided_95_lower": wilson_lower(wins, games),
    }


def training_eligible(name: str) -> bool:
    manifest = json.loads((ROOT / "artifacts" / "order_ppo" / "azure" / "checkpoints" / name / "training_manifest.json").read_text())
    return (
        manifest["status"] in {"complete", "target_kl_stop"}
        and manifest["output_model_sha256"] != manifest["initial_model_sha256"]
        and abs(float(manifest["parity"]["initial_ratio"]) - 1.0) <= 0.0001
        and float(manifest["parity"]["max_logprob_disagreement"]) <= 1e-5
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-run", default="artifacts/order_ppo/azure/run_manifest.json")
    args = parser.parse_args()
    prior = json.loads((ROOT / args.prior_run).read_text(encoding="utf-8"))
    if prior.get("status") != "complete":
        raise RuntimeError("order-PPO collection/training did not complete")
    prior_spend = float(prior.get("conservative_estimated_spend_usd", 0.0))
    if "conservative_estimated_recovery_spend_usd" in prior:
        original = json.loads((ROOT / "artifacts/order_ppo/azure/run_manifest.json").read_text(encoding="utf-8"))
        prior_spend = (
            float(original.get("conservative_estimated_spend_usd", 0.0))
            + float(prior["conservative_estimated_recovery_spend_usd"])
        )
    candidates = candidate_stages()
    bundle, digest = build_bundle(candidates)
    started = time.time()
    state_path = OUTPUT / "evaluation_manifest.json"
    if state_path.exists():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
        prior_spend = max(prior_spend, float(previous.get("prior_spend_usd", 0.0)))
        prior_spend += float(previous.get("evaluation_spend_usd", 0.0))
    state = {"status": "starting", "prior_spend_usd": prior_spend, "started_unix": started, "fast": [], "confirmation": []}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool: list(pool.map(start, WORKERS))
        time.sleep(20)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda worker: prepare(worker, bundle, digest), WORKERS))
        fast_tasks = []
        seed = 202608084000
        for candidate, order in (("first", "first"), ("second_a", "second"), ("second_b", "second")):
            for opponent, path in DEVELOPMENT.items():
                for arm, hero in (("candidate", candidates[candidate]), ("control", CONTROL)):
                    seed += 1
                    fast_tasks.append({"phase": "fast", "label": f"fast_{candidate}_{opponent}_{arm}",
                                       "candidate": candidate, "opponent_id": opponent, "arm": arm,
                                       "hero": hero, "opponent": path, "order": order, "games": 500, "seed": seed})
        state["fast"] = run_queue(fast_tasks, started, prior_spend)
        lookup = {row["task"]["label"]: row["result"] for row in state["fast"]}
        screens = {}
        for candidate in ("first", "second_a", "second_b"):
            candidate_cells = {opponent: lookup[f"fast_{candidate}_{opponent}_candidate"] for opponent in DEVELOPMENT}
            control_cells = {opponent: lookup[f"fast_{candidate}_{opponent}_control"] for opponent in DEVELOPMENT}
            screens[candidate] = fast_screen(candidate_cells, control_cells)
            screens[candidate]["training_eligible"] = training_eligible(candidate)
            screens[candidate]["passed"] &= screens[candidate]["training_eligible"]
        selection = select_checkpoints(screens["first"], {name: screens[name] for name in ("second_a", "second_b")})
        state["screens"] = screens; state["selection"] = selection
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        if not selection["passed"]:
            state["status"] = "no_checkpoint_passed"
            return 2

        exact = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "policy_weights.npz"
        first_model = exact if selection["policy_first"] == "exact_d842" else ROOT / "artifacts/order_ppo/azure/checkpoints/first/policy_weights.npz"
        second_name = selection["policy_second"]
        second_model = ROOT / "artifacts" / "order_ppo" / "azure" / "checkpoints" / second_name / "policy_weights.npz"
        package = build_final_package(SimpleNamespace(
            control="grimmsnarl_5k_reference.tar.gz", policy_first=str(first_model), policy_second=str(second_model),
            output="artifacts/order_ppo/5k_plus.tar.gz", manifest="artifacts/order_ppo/package_manifest.json",
        ))
        final_stage = OUTPUT / "final_candidate"
        reset_directory(final_stage); safe_extract(Path(package["archive"]), final_stage)
        for worker in WORKERS:
            scp_to(worker, Path(package["archive"]), "/tmp/5k_plus.tar.gz")
            ssh(worker, f"rm -rf {REMOTE}/artifacts/order_ppo/final_candidate && mkdir -p {REMOTE}/artifacts/order_ppo/final_candidate && tar -xzf /tmp/5k_plus.tar.gz -C {REMOTE}/artifacts/order_ppo/final_candidate")
        final_remote = "artifacts/order_ppo/final_candidate"
        seed = 202608085000

        # Direct strength is cheap and independently mandatory. Run it before
        # any slow authentic holdout so a conclusively weak package fails fast.
        direct_tasks = []
        for order in ("first", "second"):
            seed += 1
            direct_tasks.append({"phase": "confirmation", "label": f"direct_{order}", "kind": "direct",
                "hero": final_remote, "opponent": CONTROL, "order": order, "games": 2000, "seed": seed})
        state["confirmation"].extend(run_queue(direct_tasks, started, prior_spend))
        direct_values = {row["task"]["label"]: row["result"] for row in state["confirmation"]}
        direct = merged([direct_values["direct_first"], direct_values["direct_second"]])
        state["direct_precheck"] = direct_gate(direct)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        if not state["direct_precheck"]["passed"]:
            state["status"] = "direct_gate_failed"
            return 3

        confirm_tasks = []
        # Keep the slow authentic Alakazam cells last. Quick represented-meta,
        # safety, and self-play evidence should reject regressions first.
        for opponent in ("replay_refresh", "v2_2"):
            path = HOLDOUTS[opponent]
            for order in ("first", "second"):
                for arm, hero in (("candidate", final_remote), ("control", CONTROL)):
                    seed += 1
                    confirm_tasks.append({"phase": "confirmation", "label": f"heldout_{opponent}_{order}_{arm}",
                        "kind": "heldout", "opponent_id": opponent, "arm": arm, "hero": hero, "opponent": path,
                        "order": order, "games": 1000, "seed": seed})
        for opponent, path in SAFETY.items():
            for order in ("first", "second"):
                for arm, hero in (("candidate", final_remote), ("control", CONTROL)):
                    seed += 1
                    confirm_tasks.append({"phase": "confirmation", "label": f"safety_{opponent}_{order}_{arm}",
                        "kind": "safety", "opponent_id": opponent, "arm": arm, "hero": hero,
                        "opponent": path, "order": order, "games": 250, "seed": seed})
        for order in ("first", "second"):
            seed += 1
            confirm_tasks.append({"phase": "confirmation", "label": f"selfplay_{order}", "kind": "selfplay",
                "hero": final_remote, "opponent": final_remote, "order": order, "games": 20, "seed": seed})
        opponent = "alakazam_2_7"
        path = HOLDOUTS[opponent]
        for order in ("first", "second"):
            for arm, hero in (("candidate", final_remote), ("control", CONTROL)):
                seed += 1
                confirm_tasks.append({"phase": "confirmation", "label": f"heldout_{opponent}_{order}_{arm}",
                    "kind": "heldout", "opponent_id": opponent, "arm": arm, "hero": hero, "opponent": path,
                    "order": order, "games": 1000, "seed": seed})
        state["confirmation"].extend(run_queue(confirm_tasks, started, prior_spend))
        values = {row["task"]["label"]: row["result"] for row in state["confirmation"]}
        heldout = {opponent: {order: {
            "candidate": values[f"heldout_{opponent}_{order}_candidate"],
            "control": values[f"heldout_{opponent}_{order}_control"],
        } for order in ("first", "second")} for opponent in HOLDOUTS}
        safety = {opponent: {
            arm: merged([values[f"safety_{opponent}_{order}_{arm}"] for order in ("first", "second")])
            for arm in ("candidate", "control")
        } for opponent in SAFETY}
        direct = merged([values["direct_first"], values["direct_second"]])
        validation_path = ROOT / "artifacts" / "order_ppo" / "package_validation.json"
        run([str((ROOT / ".venv/Scripts/python.exe").resolve()), "scripts/validate_order_package.py",
             package["archive"], "--games", "20", "--output", str(validation_path)], timeout=1200)
        validation = json.loads(validation_path.read_text())
        selfplay = [values["selfplay_first"], values["selfplay_second"]]
        payload = {
            "heldout": heldout, "direct": direct, "safety": safety,
            "trained_first": selection["policy_first"] == "trained",
            "sterile_ubuntu": True,
            "deterministic_replay": bool(validation["deterministic_replay"]),
            "archive_hash_verified": hashlib.sha256(Path(package["archive"]).read_bytes()).hexdigest().upper() == package["archive_sha256"],
            "latency_passed": float(validation["latency_p99_ms"]) < 50.0,
            "kaggle_self_play_passed": all(
                cell["hero_policy_errors"] == 0 and cell["opponent_policy_errors"] == 0 for cell in selfplay
            ),
        }
        promotion = confirmation_gate(payload)
        promotion.update({"selection": selection, "package": package, "validation": validation})
        promotion_path = ROOT / "artifacts" / "order_ppo" / "promotion_manifest.json"
        promotion_path.write_text(json.dumps(promotion, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        state["promotion"] = promotion; state["status"] = "passed" if promotion["passed"] else "confirmation_failed"
        if promotion["passed"]:
            run([str((ROOT / ".venv/Scripts/python.exe").resolve()), "scripts/upload_order_ppo_candidate.py"], timeout=1200)
        return 0 if promotion["passed"] else 3
    except Exception as exc:
        state["status"] = "failed"; state["error"] = repr(exc)
        raise
    finally:
        ended = time.time(); state["ended_unix"] = ended
        state["evaluation_spend_usd"] = (ended - started) / 3600 * len(WORKERS) * RATE_PER_WORKER_HOUR
        state["combined_estimated_spend_usd"] = prior_spend + state["evaluation_spend_usd"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool: list(pool.map(deallocate, WORKERS))


if __name__ == "__main__":
    raise SystemExit(main())
