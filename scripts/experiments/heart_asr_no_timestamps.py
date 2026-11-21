"""One explicit Heart decode change, using an unchanged, hash-pinned runner.

No model runtime is imported by loading or inspecting this wrapper. The private
runner's __file__ is its child entry point; base_runner records its actual source.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = Path(__file__).resolve()
BASE_PATH = ROOT / "scripts/experiments/heart_asr.py"
BASE_SHA = "b68b3b77aeb8446f1dee27357ed433964ff6d77e92cd10d03c341a5752fe1dc7"
PROPOSAL = ROOT / "build/generation-next/heart-cpu-research/no-timestamps-proposal-v1.json"
PROPOSAL_SHA = "48371ba5b75c04048c06fb3eac80a6e1d56579a5a4be1b55489d8eada0c1767b"
ORIGINAL_PROPOSAL_SHA = "d8e8951e071720bb741d6f19aeb0aeb59fb666f588041a8aa3367780cb013d15"
DEFAULT_OUTPUT = ROOT / "build/generation-next/heart-asr/no-timestamps-v1"
HEART_PYTHON = ROOT / "build/generation-next/heart-transcriptor/env/bin/python"
HYPOTHESIS_DECISION = {
    "path": str(ROOT / "build/generation-next/heart-transcriptor/hypothesis-decision-no-timestamps-before-asr.json"),
    "sha256": "4cd426ab037a771f0d55815b6074fe3fbb9319efeb2422455663e0dcad1d6e36"}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_runner(path, expected):
    # Check bytes before executing any source from the runner.
    if digest(path) != expected:
        raise ValueError("Frozen Heart runner changed before import")
    spec = importlib.util.spec_from_file_location("_heart_no_timestamps_runner", path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded  # Required by nested dataclass type resolution.
    spec.loader.exec_module(loaded)
    return loaded


base = load_runner(BASE_PATH, BASE_SHA)
BASE_DECODE = deepcopy(base.DECODE)
VARIANT_DECODE = dict(deepcopy(BASE_DECODE), without_timestamps=True)
_original_own_sources = base.own_sources
_original_verify_plan = base.verify_plan


def guard_variant():
    if digest(BASE_PATH) != BASE_SHA or base.DECODE != VARIANT_DECODE:
        raise ValueError("Only without_timestamps=True may differ from the frozen runner")
    if base.PROPOSAL_SHA != PROPOSAL_SHA or Path(base.__file__).resolve() != WRAPPER:
        raise ValueError("Wrapper proposal or child entry point changed")


def own_sources():
    guard_variant()
    sources = _original_own_sources()
    # The base runner uses __file__ for both launch argv and adapter provenance.
    # Preserve its real source separately; no file on disk is modified.
    sources["base_runner"] = {"path": str(BASE_PATH), "sha256": BASE_SHA}
    if sources["adapter"]["path"] != str(WRAPPER):
        raise ValueError("Child launch and adapter provenance must both name the wrapper")
    return sources


def validate_proposal_delta(proposed, original):
    if proposed["inference"] != dict(original["inference"], without_timestamps=True):
        raise ValueError("Proposal must change only without_timestamps in inference")
    if proposed["source_model"] != dict(original["source_model"], local_bytes_verified=True):
        raise ValueError("Source model differs beyond its verified status")
    metadata = {"created_utc", "status", "label", "baseline", "rms_plan_sha256",
                "audio_freeze_sha256", "remaining_preconditions", "ready_to_execute",
                "original_proposal", "prior_heart_plan", "prior_heart_freeze",
                "conversion_freeze", "decoding_evidence", "diagnostics",
                "expansion_decision", "rationale", "inference", "source_model"}
    for key in (set(original) | set(proposed)) - metadata:
        if key not in original or key not in proposed or original[key] != proposed[key]:
            raise ValueError(f"Non-metadata proposal setting changed: {key}")


def checked_proposal(path):
    if digest(path) != PROPOSAL_SHA:
        raise ValueError("Expected the reviewed single-change proposal")
    proposed = base.load(path)
    if proposed["original_proposal"]["sha256"] != ORIGINAL_PROPOSAL_SHA:
        raise ValueError("Original Heart proposal identity differs")
    original = base.load(base.check(proposed["original_proposal"]))
    validate_proposal_delta(proposed, original)
    for key in ("prior_heart_plan", "prior_heart_freeze", "conversion_freeze",
                "diagnostics", "expansion_decision"):
        base.check(proposed[key])
    for item in proposed["decoding_evidence"].values():
        base.check(item)
    # This second predeclared rule compares to Heart v2, separately from Turbo.
    base.check(HYPOTHESIS_DECISION)
    return proposed


def verify_plan(output):
    guard_variant()
    settings = _original_verify_plan(output)
    checked_proposal(base.check(settings["proposal"]))
    return settings


# This is a private imported module, not the normally imported heart_asr module.
# ROOT and helper paths were resolved before substituting the child entry point.
base.__file__ = str(WRAPPER)
base.DECODE = deepcopy(VARIANT_DECODE)
base.PROPOSAL_SHA = PROPOSAL_SHA
base.own_sources = own_sources
base.verify_plan = verify_plan


def plan(args):
    guard_variant()
    checked_proposal(args.proposal)
    base.plan(args)


def inspect_variant():
    guard_variant()
    return {"sources": own_sources(), "decode": base.DECODE, "model": base.MODEL,
            "resources": base.RESOURCES, "synthetic": base.CONTROL, "arm": base.ARM,
            "proposal_sha256": PROPOSAL_SHA, "child_entry_point": str(WRAPPER),
            "hypothesis_decision": HYPOTHESIS_DECISION,
            "model_loaded": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "inspect", "selftest", "synthetic", "execute", "_worker"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proposal", type=Path, default=PROPOSAL)
    parser.add_argument("--baseline", type=Path, default=ROOT / "build/generation-next/rms-vad-asr/v3")
    parser.add_argument("--conversion-freeze", type=Path)
    parser.add_argument("--python", type=Path, default=HEART_PYTHON)
    parser.add_argument("--song", choices=base.PILOT)
    parser.add_argument("--control", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "plan" and args.conversion_freeze is None:
        parser.error("plan requires an existing --conversion-freeze")
    if args.command == "_worker" and not args.control and args.song is None:
        parser.error("worker requires --song or --control")
    guard_variant()
    if args.command == "inspect":
        print(base.shared.json.dumps(inspect_variant(), indent=2))
    elif args.command == "selftest":
        print(base.shared.json.dumps(base.selftest(), indent=2))
    else:
        {"plan": plan, "synthetic": base.synthetic, "execute": base.execute,
         "_worker": base.worker}[args.command](args)


if __name__ == "__main__":
    main()
