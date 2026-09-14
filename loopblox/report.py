"""Render a recorded run as expandable, read-only Blox. No graph execution."""

import argparse
from collections import Counter, defaultdict
from html import escape
import json
from pathlib import Path

from loopblox.runtime.model import usage_tokens
from loopblox.runtime.io import atomic_text


def summarize_trace(record):
    """Public execution facts, without inferring progress, causality or task success."""
    components = {}
    owners = {}
    for block in record["component_calls"]:
        name = block["component"]
        # Invalid candidate calls are recorded before contract rejection, too.
        owner = name if isinstance(name, str) else "invalid name: " + json.dumps(name, sort_keys=True)
        owners[block["id"]] = owner
        item = components.setdefault(owner, dict(
            invocation_ids=[], statuses={}, direct_calls=0, model_attempts=0,
            charged_output_tokens=0, unknown_output_attempts=0))
        item["invocation_ids"].append(block["id"])
        item["statuses"][block["status"]] = item["statuses"].get(block["status"], 0) + 1
        item["direct_calls"] += block["parent_id"] is None
    for call in record["model_calls"]:
        item = components[owners[call["request"]["component_id"]]]
        item["model_attempts"] += 1
        item["charged_output_tokens"] += call["charged_output_tokens"]
        item["unknown_output_attempts"] += usage_tokens(call["usage"], "completion_tokens") is None

    requests = [event for event in record["history"] if event["type"] == "tool_call"]
    results = {event["action_id"]: event for event in record["history"] if event["type"] == "tool_result"}
    tools, repeated = {}, []
    previous, streak = None, None
    for request in requests:
        result = results.get(request["action_id"])
        item = tools.setdefault(request["capability_id"], dict(requests=0, outcomes={}, effects={}))
        item["requests"] += 1
        status = result["status"] if result else "missing_result"
        effects = result["effects"] if result else "unknown"
        item["outcomes"][status] = item["outcomes"].get(status, 0) + 1
        item["effects"][effects] = item["effects"].get(effects, 0) + 1
        # Host IDs differ on every attempt; compare actual arguments and returned values.
        signature = json.dumps([request["capability_id"], request["arguments"],
                                status, result["result"], effects], sort_keys=True) if result else None
        if signature is not None and signature == previous:
            if len(streak["action_ids"]) == 1:
                repeated.append(streak)
            streak["action_ids"].append(request["action_id"])
        else:
            streak = dict(capability_id=request["capability_id"], action_ids=[request["action_id"]])
        previous = signature
    return dict(
        components=components, tools=tools, model_attempts=len(record["model_calls"]),
        model_statuses=dict(Counter(call["status"] for call in record["model_calls"])),
        repeated_action_results=repeated,
        longest_identical_action_result_streak=max((len(row["action_ids"]) for row in repeated), default=0),
        interpretation="Counts are actual invocations and owned requests, never parent cost rollups. "
                       "Identical consecutive tool requests/results are not proof of stalled progress. "
                       "Component presence and outcome differences do not establish causal effects. "
                       "Environment model calls are accounted separately in task usage; private user traces are excluded.",
    )


def write_trace_report(record, path):
    children, models, tools = defaultdict(list), defaultdict(list), defaultdict(list)
    for block in record["component_calls"]:
        children[block["parent_id"]].append(block)
    for number, call in enumerate(record["model_calls"], 1):
        models[call["request"]["component_id"]].append((number, call))
    for event in record["history"]:
        if event["type"] in {"tool_call", "tool_result"}:
            tools[event["component_id"]].append(event)

    def payload(title, value):
        return (f'<details class="payload"><summary>{escape(title)}</summary><pre>'
                f'{escape(json.dumps(value, ensure_ascii=False, indent=2))}</pre></details>')

    def mechanism(title, kind, status, value, depth, owner):
        return (f'<details class="mechanism" data-depth="{depth}"><summary>'
                f'<span class="depth">D{depth}</span> <strong>{escape(title)}</strong>'
                f'<span class="status">{escape(status)}</span>'
                f'<small>{escape(kind)} · 固定执行机制 · 所属组件：{escape(owner)}</small>'
                f'</summary><pre>{escape(json.dumps(value, ensure_ascii=False, indent=2))}</pre></details>')

    def render(block, ancestors=()):
        depth = len(ancestors) + 1
        owner = f'{block["component"]} · {block["id"]}'
        nested = [render(child, (*ancestors, owner)) for child in children[block["id"]]]
        own_models = models[block["id"]]
        tool_calls = [event for event in tools[block["id"]] if event["type"] == "tool_call"]
        tool_results = {event["action_id"]: event for event in tools[block["id"]]
                        if event["type"] == "tool_result"}
        own_tools = len(tool_calls)
        model_count = len(own_models) + sum(item[1] for item in nested)
        tool_count = own_tools + sum(item[2] for item in nested)
        name = block["component"]
        spec = record["library"].get(name, {}) if isinstance(name, str) else {}
        category = escape(spec.get("category", "unknown"))
        # Family metadata comes from this run's frozen library, never today's definitions.
        family = spec.get("family")
        family_label = (f'<small>能力类别：{escape(family["label"])} · '
                        f'返回类型：ref&lt;{category}&gt;</small>' if family else '')
        duration = block.get("elapsed_seconds", 0)
        start = block["start_seconds"]
        composite = "implementation_source" in spec
        kind = "组合组件" if composite else "叶组件" if spec else "未识别组件"
        location = "controller 直接调用" if not ancestors else "父组件内部调用"
        if ancestors:
            boundary = "内部实现固定"
        else:
            exposed = isinstance(name, str) and name in record["exposed"]
            boundary = "本实验开放组合与目录选项" if exposed else "本实验未开放此调用"
        ancestry = escape("完整 Loop / " + " / ".join(ancestors))
        details = payload("本次输入与结果", {key: block[key] for key in
                          ("arguments", "value", "error", "error_type") if key in block})
        for number, call in own_models:
            details += mechanism(f"模型请求 #{number}", "Model Execution", call["status"],
                                 call, depth + 1, owner)
        for event in tool_calls:
            result = tool_results.get(event["action_id"])
            details += mechanism(f'工具动作 · {event["capability_id"]}', "Action Runtime",
                                 result["status"] if result else event["status"],
                                 dict(attempt=event, outcome=result), depth + 1, owner)
        if composite:
            details += ('<details class="payload"><summary>固定实现 · Python</summary><pre>'
                        + escape(spec["implementation_source"]) + '</pre></details>')
        if nested:
            details += '<div class="children">' + ''.join(item[0] for item in nested) + '</div>'
        opened = ' open' if block["parent_id"] is None else ''
        html = (
            f'<details class="blox {category}" data-depth="{depth}"{opened}><summary>'
            f'<span class="depth">D{depth}</span> '
            f'<span class="identity">{escape(block["id"])} · {escape(str(name))}</span>'
            f'<span class="status">{escape(block["status"])}</span>'
            f'<small>{kind} · {location} · {boundary}</small>'
            f'{family_label}'
            f'<small class="ancestry">所属组合：{ancestry}</small>'
            f'<small>开始 {start:.3f}s · 用时 {duration:.3f}s · '
            f'模型 {model_count} 次 · 动作 {tool_count} 次（含内部调用）</small>'
            f'</summary>{details}</details>'
        )
        return html, model_count, tool_count

    calls = record["model_calls"]
    unknown = sum(usage_tokens(call["usage"], "completion_tokens") is None for call in calls)
    charged = sum(call["charged_output_tokens"] for call in calls)
    tree = ''.join(render(block)[0] for block in children[None])
    scope = escape(record["scope"])
    page = f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>LoopBlox · {scope}</title>
<style>
body{{font:15px/1.6 system-ui,sans-serif;background:#f5f3ee;color:#242b32;margin:0}}
main{{max-width:1080px;margin:auto;padding:40px 24px 72px}}h1{{font-size:30px;letter-spacing:-1px}}
.eyebrow{{color:#486855;font-weight:650}}.muted,small{{color:#697079}}.stats{{display:flex;gap:12px;flex-wrap:wrap}}
.stat{{background:white;border:1px solid #dddcd5;border-radius:10px;padding:12px 18px}}.stat b{{font-size:22px}}
.blox{{background:white;border:1px solid #d7d9d7;border-left:5px solid #839f8c;border-radius:10px;margin:14px 0}}
.blox.decision{{border-left-color:#628cb9}}.blox.execution{{border-left-color:#c2944f}}
.blox.work{{border-left-color:#8176a8}}summary{{cursor:pointer;padding:12px 14px}}summary small{{display:block;margin-left:17px}}
.identity{{font-weight:650}}.status{{float:right;color:#697079;font-size:13px}}
.depth{{display:inline-block;background:#e8edf6;color:#3e557f;border-radius:5px;padding:1px 7px;font-size:12px;font-weight:700;margin-right:5px}}
.legend{{background:#fff;border:1px solid #d7d9d7;border-radius:10px;padding:18px;margin:24px 0}}
.legend h2{{margin:0 0 10px;font-size:20px}}.legend p{{margin:10px 0 0}}
.legend table{{width:100%;border-collapse:collapse}}.legend th,.legend td{{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid #eceeea}}
.run{{border:2px solid #81928a;border-radius:12px;padding:18px;background:#eeefe9}}
.run-title{{font-size:19px;font-weight:650}}.run-title small{{display:block;font-size:13px;font-weight:400}}
.mechanism{{margin:10px 14px 14px 28px;border:1px dashed #abb4c1;border-radius:8px;background:#f5f7fa}}
.mechanism pre{{margin:0 12px 12px}}.ancestry{{overflow-wrap:anywhere}}
.children{{margin:12px 14px 16px 28px;border-left:1px dashed #bac0bd;padding-left:12px}}
.payload{{margin:6px 12px}}.payload summary{{padding:6px;color:#58616b}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f6f4;padding:14px;border-radius:6px;font-size:12px}}
footer{{margin-top:32px;border-top:1px solid #d7d9d7;padding-top:16px;color:#697079}}
</style><main>
<div class="eyebrow">LoopBlox / 实际运行</div><h1>{scope}</h1>
{payload("环境模型用量（已计入任务总预算；隐藏指令不进入 controller 轨迹）", record["environment_usage"]) if "environment_usage" in record else ""}
<p>{escape(record["status"])} · {escape(str(record.get("stop_reason", "")))}</p>
<div class="stats"><div class="stat"><b>{len(calls)}</b> Controller 模型请求</div>
<div class="stat"><b>{record["actions_executed"]}</b> 工具动作</div>
<div class="stat"><b>{charged}</b> 已计入输出额度</div>
<div class="stat"><b>{record.get("elapsed_seconds", 0):.2f}s</b> 总用时</div></div>
<p class="muted">{unknown} 次请求的输出用量未知；额度包含相应预留量。总量来自实际请求与动作，未重复累加父积木汇总。完成状态不代表隐藏评测通过。</p>
{payload("本次主输入", record["history"][0]["task"])}
{payload("本次开放的外层积木与选项", record["exposed"])}
{payload("运行返回值", record.get("result"))}
{payload("执行事实摘要（组件触发、工具结果与连续重复）", summarize_trace(record))}
<section class="legend"><h2>每一步属于哪里？</h2>
<table><thead><tr><th>展开位置</th><th>含义</th></tr></thead><tbody>
<tr><td><span class="depth">D0</span> 完整 Loop</td><td>本次主输入到 controller 交还控制权；完整评价单位。</td></tr>
<tr><td><span class="depth">D1</span> 外层直接调用</td><td>当前为 controller 编排的子组件；历史运行按冻结记录展示。</td></tr>
<tr><td><span class="depth">D2+</span> 逐层展开内部</td><td>组件内部的子调用，或它产生的实际模型请求、工具动作；查看每步的类型与所属组件。</td></tr>
</tbody></table>
<p>能力类别来自本次运行冻结的组件目录，不规定调用顺序或修改权限。这里的 D 表示真实调用深度；当前 controller 直接组合子组件，模型与工具请求显示在所属组件下。历史记录按当时的实际父子关系展示。</p>
<p>Loop level 看外层编排；Loop exec level 看某个组件展开后的内部执行。组合组件、叶组件与底层请求会分别标注；Model Execution / Action Runtime 表示行为职责，不是层数。展开查看不会扩大本次实验的修改权限。</p></section>
<h2>真实调用路径</h2><section class="run" data-depth="0">
<div class="run-title"><span class="depth">D0</span> 完整 Loop · 本次 task run
<small>外层 controller 拥有继续、返工和最终返回的决定权。</small></div>
{tree or '<p>本次没有组件调用。</p>'}</section>
<footer>点击积木查看本次输入、结果和内部调用。固定实现展示可能的行为；调用路径只展示实际发生的分支。
这是 LoopBlox 组件运行记录，不是四个原生 harness 的执行证明。页面只读，无编辑或执行功能。</footer>
</main></html>'''
    atomic_text(Path(path), page)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    write_trace_report(json.loads(args.trace.read_text()), args.output or args.trace.with_suffix(".html"))
