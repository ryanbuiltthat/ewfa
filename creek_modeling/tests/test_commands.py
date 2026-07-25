"""Plain-assert tests for command handling (no pytest, no broker).

Run: python creek_modeling/tests/test_commands.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.commands import CommandProcessor, CommandQueue  # noqa: E402


def test_command_from_topic():
    assert CommandQueue.command_from_topic("creek/cmd/retrain") == "retrain"
    assert CommandQueue.command_from_topic("creek/cmd/run_inference") == "run_inference"
    assert CommandQueue.command_from_topic("creek/flood_probability") is None
    assert CommandQueue.command_from_topic("cmd/promote") == "promote"


def test_queue_offer_and_drain_fifo():
    q = CommandQueue()
    q.offer("run_inference")
    q.offer("retrain")
    assert q.drain() == ["run_inference", "retrain"]
    assert q.drain() == []  # drained empties it


def test_known_command_runs_handler():
    calls = []
    proc = CommandProcessor({"retrain": lambda: calls.append("x") or "did retrain"})
    res = proc.handle("retrain")
    assert res.ok is True
    assert res.message == "did retrain"
    assert calls == ["x"]


def test_unknown_command_rejected():
    proc = CommandProcessor({})
    res = proc.handle("delete_everything")
    assert res.ok is False
    assert "unknown command" in res.message


def test_missing_handler_for_known_command():
    proc = CommandProcessor({})  # 'promote' is known but has no handler wired
    res = proc.handle("promote")
    assert res.ok is False
    assert "no handler" in res.message


def test_handler_exception_is_caught_not_raised():
    def boom():
        raise ValueError("kaboom")

    proc = CommandProcessor({"retrain": boom})
    res = proc.handle("retrain")
    assert res.ok is False
    assert "ValueError" in res.message
    assert "kaboom" in res.message


def test_handler_returning_none_defaults_to_ok():
    proc = CommandProcessor({"run_inference": lambda: None})
    res = proc.handle("run_inference")
    assert res.ok is True
    assert res.message == "ok"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()
