# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Inference client, priority queue with preemption, KoboldCpp arguments (P1-05)."""

from __future__ import annotations

import asyncio
import itertools
import sys

import httpx
import pytest

from moritz_agent.config.settings import Settings, load_settings
from moritz_agent.inference import (
    InferenceAborted,
    InferenceClient,
    InferenceQueue,
    InferenceTimeout,
    InferenceUnavailable,
    Priority,
)
from moritz_agent.inference.process import build_argv

from .fake_model import FakeModel, text_chunks, tool_chunks

MESSAGES = [{"role": "user", "content": "Hallo"}]


def run(coro):
    return asyncio.run(coro)


def make(model: FakeModel, **kwargs) -> InferenceClient:
    return InferenceClient("http://127.0.0.1:5001", transport=model.transport(), **kwargs)


# -- the client -----------------------------------------------------------------------------------------
def test_streaming_text():
    async def scenario():
        model = FakeModel()
        client = make(model)
        seen: list[str] = []
        result = await client.chat(MESSAGES, max_tokens=50, temperature=0.2, on_text=seen.append)
        await client.aclose()
        return model, result, seen

    model, result, seen = run(scenario())
    assert result.text == "Hallo Welt" and seen == ["Hallo", " Welt"]
    assert (
        result.finish_reason == "stop"
        and result.first_token_ms is not None
        and result.total_ms >= 0
    )
    assert (result.prompt_tokens, result.completion_tokens) == (20, 2)
    body = model.requests[0]
    assert body["stream"] is True and body["max_tokens"] == 50 and body["temperature"] == 0.2
    assert body["messages"] == MESSAGES and body["genkey"].startswith("MA_") and "tools" not in body


def test_async_callbacks_are_awaited():
    async def scenario():
        client = make(FakeModel())
        seen: list[str] = []

        async def on_text(piece: str) -> None:
            seen.append(piece.upper())

        await client.chat(MESSAGES, on_text=on_text)
        return seen

    assert run(scenario()) == ["HALLO", " WELT"]


def test_tool_calls_are_assembled_from_fragments():
    async def scenario():
        model = FakeModel()
        model.script = [tool_chunks("get_weather", '{"place": "Berlin", "when": "morgen"}')]
        client = make(model)
        tools = [
            {
                "type": "function",
                "function": {"name": "get_weather", "parameters": {"type": "object"}},
            }
        ]
        result = await client.chat(MESSAGES, tools=tools)
        return model, result

    model, result = run(scenario())
    assert model.requests[0]["tools"][0]["function"]["name"] == "get_weather"
    assert model.requests[0]["tool_choice"] == "auto"
    [call] = result.tool_calls
    assert (call.id, call.name, call.arguments) == (
        "call_1",
        "get_weather",
        {"place": "Berlin", "when": "morgen"},
    )
    assert result.finish_reason == "tool_calls" and result.text == ""


def test_broken_tool_arguments_are_flagged_not_raised():
    async def scenario():
        model = FakeModel()
        model.script = [tool_chunks("get_weather", '{"place": "Ber')]
        return await make(model).chat(
            MESSAGES, tools=[{"type": "function", "function": {"name": "x"}}]
        )

    [call] = run(scenario()).tool_calls
    assert (
        call.valid_json is False
        and call.arguments == {}
        and call.raw_arguments.startswith('{"place"')
    )


def test_errors_are_classified():
    async def scenario(step):
        model = FakeModel()
        model.script = [step]
        return await make(model).chat(MESSAGES)

    with pytest.raises(InferenceUnavailable):
        run(scenario(500))
    with pytest.raises(InferenceUnavailable):
        run(scenario(httpx.ConnectError("refused")))
    with pytest.raises(InferenceTimeout):
        run(scenario(httpx.ReadTimeout("slow")))


def test_abort_stops_a_running_generation():
    async def scenario():
        model = FakeModel()
        model.gate = True
        model.default = text_chunks("a", "b", "c", "d")
        client = make(model)
        task = asyncio.ensure_future(client.chat(MESSAGES, genkey="MA_test"))
        await model.wait_for_running()
        await client.abort("MA_test")
        with pytest.raises(InferenceAborted):
            await asyncio.wait_for(task, 2)
        return model

    model = run(scenario())
    assert model.abort_calls == ["MA_test"]


def test_health_perf_and_token_count():
    async def scenario():
        model = FakeModel()
        client = make(model)
        results = (await client.health(), await client.perf(), await client.token_count("x" * 40))
        model.model_loaded = False
        return results, await client.health()

    (healthy, perf, tokens), unhealthy = run(scenario())
    assert healthy and perf["total_gens"] == 3 and tokens == 10 and not unhealthy


def test_health_is_false_when_nothing_listens():
    async def scenario():
        def refuse(request):
            raise httpx.ConnectError("refused")

        return await InferenceClient(
            "http://127.0.0.1:1", transport=httpx.MockTransport(refuse)
        ).health()

    assert run(scenario()) is False


# -- the queue --------------------------------------------------------------------------------------------
async def start_gated(model: FakeModel, queue: InferenceQueue, priority: Priority, label: str):
    task = asyncio.ensure_future(queue.chat(MESSAGES, priority=priority, label=label))
    await model.wait_for_running()
    return task


def test_jobs_run_by_priority_then_first_come():
    async def scenario():
        model = FakeModel()
        model.gate = True
        queue = InferenceQueue(make(model))
        order: list[str] = []

        async def job(label: str, priority: Priority):
            await queue.chat(MESSAGES, priority=priority, label=label)
            order.append(label)

        first = asyncio.ensure_future(job("first", Priority.INTERACTIVE))
        await model.wait_for_running()
        rest = [
            asyncio.ensure_future(job("bg", Priority.BACKGROUND)),
            asyncio.ensure_future(job("web1", Priority.INTERACTIVE)),
            asyncio.ensure_future(job("web2", Priority.INTERACTIVE)),
            asyncio.ensure_future(job("voice", Priority.VOICE)),
        ]
        await asyncio.sleep(0.05)
        queue.preempt_wait_s = 999  # nobody may interrupt "first" here
        model.release_all()
        await asyncio.wait_for(asyncio.gather(first, *rest), 5)
        await queue.aclose()
        return order

    assert run(scenario()) == ["first", "voice", "web1", "web2", "bg"]


def test_the_phone_interrupts_background_work_at_once_and_it_runs_again_later():
    async def scenario():
        model = FakeModel()
        model.gate = True
        model.default = text_chunks("x", "y")
        queue = InferenceQueue(make(model), preempt_wait_s=5)
        background = asyncio.ensure_future(
            queue.chat(MESSAGES, priority=Priority.BACKGROUND, label="bg")
        )
        await model.wait_for_running()
        first_key = next(iter(model.running))
        phone = asyncio.ensure_future(queue.chat(MESSAGES, priority=Priority.PHONE, label="phone"))
        await asyncio.sleep(0.2)
        aborted_early = first_key in model.abort_calls
        model.release_all()
        done = await asyncio.wait_for(asyncio.gather(phone, background), 5)
        await queue.aclose()
        return aborted_early, queue.preemptions, [r.text for r in done], len(model.requests)

    aborted_early, preemptions, texts, requests = run(scenario())
    assert (
        aborted_early and preemptions == 1 and texts == ["xy", "xy"] and requests == 3
    )  # bg, phone, bg again


def test_the_phone_waits_for_a_short_interactive_answer_but_not_forever():
    async def scenario(wait):
        model = FakeModel()
        model.gate = True
        queue = InferenceQueue(make(model), preempt_wait_s=wait)
        web = asyncio.ensure_future(
            queue.chat(MESSAGES, priority=Priority.INTERACTIVE, label="web")
        )
        await model.wait_for_running()
        phone = asyncio.ensure_future(queue.chat(MESSAGES, priority=Priority.PHONE, label="phone"))
        await asyncio.sleep(0.05)
        early = list(model.abort_calls)
        await asyncio.sleep(wait + 0.2)
        model.release_all()
        await asyncio.wait_for(asyncio.gather(web, phone), 5)
        await queue.aclose()
        return early, list(model.abort_calls)

    early, later = run(scenario(0.3))
    assert early == [] and len(later) == 1  # not at once, but after the waiting time


def test_no_abort_when_the_running_job_finishes_within_the_waiting_time():
    async def scenario():
        model = FakeModel()
        model.gate = True
        queue = InferenceQueue(make(model), preempt_wait_s=1.0)
        web = asyncio.ensure_future(queue.chat(MESSAGES, priority=Priority.INTERACTIVE))
        await model.wait_for_running()
        phone = asyncio.ensure_future(queue.chat(MESSAGES, priority=Priority.PHONE))
        await asyncio.sleep(0.05)
        model.release_all()
        await asyncio.wait_for(asyncio.gather(web, phone), 5)
        await queue.aclose()
        return model.abort_calls

    assert run(scenario()) == []


def test_every_generation_has_its_own_key():
    async def scenario():
        model = FakeModel()
        queue = InferenceQueue(make(model))
        await asyncio.gather(*(queue.chat(MESSAGES, priority=Priority.PHONE) for _ in range(4)))
        await queue.aclose()
        return [r["genkey"] for r in model.requests]

    keys = run(scenario())
    assert len(set(keys)) == 4 and all(k.startswith("MA_") for k in keys)


def test_a_waiting_job_that_is_cancelled_never_runs():
    async def scenario():
        model = FakeModel()
        model.gate = True
        queue = InferenceQueue(make(model), preempt_wait_s=999)
        blocker = asyncio.ensure_future(queue.chat(MESSAGES, priority=Priority.INTERACTIVE))
        await model.wait_for_running()
        waiting = asyncio.ensure_future(queue.chat(MESSAGES, priority=Priority.BACKGROUND))
        await asyncio.sleep(0.05)
        waiting.cancel()
        await asyncio.sleep(0.05)
        model.release_all()
        await asyncio.wait_for(blocker, 5)
        await queue.aclose()
        return len(model.requests), queue.depth()

    assert run(scenario()) == (1, 0)


def test_hanging_up_stops_the_running_generation():
    async def scenario():
        model = FakeModel()
        model.gate = True
        queue = InferenceQueue(make(model))
        task = asyncio.ensure_future(queue.chat(MESSAGES, priority=Priority.PHONE))
        await model.wait_for_running()
        key = next(iter(model.running))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.1)
        await queue.aclose()
        return key in model.abort_calls

    assert run(scenario())


def test_errors_reach_the_caller_and_the_queue_keeps_working():
    async def scenario():
        model = FakeModel()
        model.script = [500]
        queue = InferenceQueue(make(model))
        with pytest.raises(InferenceUnavailable):
            await queue.chat(MESSAGES, priority=Priority.PHONE)
        good = await queue.chat(MESSAGES, priority=Priority.PHONE)
        await queue.aclose()
        return good.text, queue.completed

    assert run(scenario()) == ("Hallo Welt", 1)


# -- starting KoboldCpp --------------------------------------------------------------------------------------
def test_koboldcpp_arguments(tmp_path):
    settings = load_settings()
    argv = build_argv(settings, tmp_path, 5123, python="/usr/bin/python3")
    assert argv[0] == "/usr/bin/python3" and argv[1] == str(tmp_path / "koboldcpp.py")
    pairs = dict(itertools.pairwise(argv))
    assert (
        pairs["--host"] == "127.0.0.1" and pairs["--port"] == "5123"
    )  # never reachable from the LAN
    assert pairs["--contextsize"] == "4096" and pairs["--parallelrequests"] == "1"
    assert pairs["--model"].endswith("Qwen3-30B-A3B-Instruct-2507-UD-Q3_K_XL.gguf")
    assert (
        pairs["--moecpu"] == "24" and pairs["--threads"] == "12" and pairs["--blasthreads"] == "12"
    )
    for flag in (
        "--usecuda",
        "--jinja",
        "--flashattention",
        "--skiplauncher",
        "--quiet",
        "--websearch",
    ):
        assert flag in argv


def test_koboldcpp_arguments_without_gpu_or_websearch(tmp_path):
    settings = load_settings()
    cfg = settings.inference.model_copy(
        update={
            "use_cuda": False,
            "websearch_fallback": False,
            "moe_cpu_layers": 0,
            "chat_adapter": "config/nothink.json",
        }
    )
    argv = build_argv(settings.model_copy(update={"inference": cfg}), tmp_path, 5124)
    assert "--usecuda" not in argv and "--websearch" not in argv and "--moecpu" not in argv
    assert "--flashattention" not in argv  # only with CUDA
    assert argv[argv.index("--gpulayers") + 1] == "0"
    assert argv[argv.index("--chatcompletionsadapter") + 1] == str(tmp_path / "config/nothink.json")


def test_koboldcpp_runs_with_its_own_build_environment_once_it_is_built(tmp_path):
    from moritz_agent.inference.process import koboldcpp_built, koboldcpp_python

    settings = Settings()
    engine = tmp_path / "koboldcpp"
    cfg = settings.inference.model_copy(update={"koboldcpp_script": "koboldcpp/koboldcpp.py"})
    settings = settings.model_copy(update={"inference": cfg})
    assert koboldcpp_python(settings, tmp_path) == sys.executable
    assert not koboldcpp_built(settings, tmp_path)
    conda = engine / "conda" / "envs" / "linux" / "bin"
    conda.mkdir(parents=True)
    (conda / "python").write_text("")
    (engine / "koboldcpp_cublas.so").write_text("")
    assert koboldcpp_python(settings, tmp_path) == str(conda / "python")
    assert koboldcpp_built(settings, tmp_path)
    cpu = settings.model_copy(update={"inference": cfg.model_copy(update={"use_cuda": False})})
    assert not koboldcpp_built(cpu, tmp_path)  # the CPU library is a different one
