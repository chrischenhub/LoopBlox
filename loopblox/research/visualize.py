"""Build a standalone, read-only visualization of a continuous research campaign."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import difflib
from html import escape
import json
import re
from pathlib import Path

from loopblox.runtime.io import atomic_text, digest


def public_directory(path):
    path = Path(path).resolve()
    if (path / 'research/public').is_dir():
        return path / 'research/public', path
    if (path / 'public').is_dir():
        return path / 'public', path.parent
    if path.name == 'public' and (path / 'candidates').is_dir():
        protected = path.parent.parent if path.parent.name == 'research' else path
        return path, protected
    raise ValueError('Expected a campaign directory, research directory, or research/public directory.')


def execution_patterns(trace):
    """Group actual root invocations at observations; preserve pattern occurrence order.

    A pattern is only a component/status sequence, not equivalent arguments or
    behavior. No inferred branches, source parsing, or candidate execution.
    """
    patterns, order, pending = [], [], []
    library = trace['library']

    def record_chunk():
        signature = [(call['component'], call['status']) for call in pending]
        existing = next((i for i, item in enumerate(patterns) if item['sequence'] == signature), None)
        if existing is None:
            existing = len(patterns)
            patterns.append(dict(sequence=signature, occurrences=[]))
        patterns[existing]['occurrences'].append([call['id'] for call in pending])
        if order and order[-1]['pattern'] == existing:
            order[-1]['repeat'] += 1
        else:
            order.append(dict(pattern=existing, repeat=1))
        pending.clear()

    for call in trace['component_calls']:
        if call['parent_id'] is not None:
            continue
        pending.append(call)
        name = call['component']
        spec = library.get(name, {}) if isinstance(name, str) else {}
        if spec.get('category') == 'observation':
            record_chunk()
    if pending:
        record_chunk()
    return dict(patterns=patterns, order=order, trace_status=trace['status'])


def read_campaign(public, task=None):
    """Read only public, individually atomic records. Reports never refresh the host."""
    public = Path(public).resolve()
    provenance = {}

    def read(relative, *, optional=False, text=False):
        path = (public / relative).resolve()
        if not path.is_relative_to(public) or 'private' in path.relative_to(public).parts:
            raise ValueError(f'Record points outside public evidence: {relative}')
        if optional and not path.exists():
            return None
        raw = path.read_bytes()
        provenance[str(path.relative_to(public))] = digest(raw)
        return raw.decode() if text else json.loads(raw)

    progress = read('progress.json')
    checkpoints = [read(str(p.relative_to(public))) for p in sorted((public / 'checkpoints').glob('*.json'))]
    checkpoints.sort(key=lambda c: c['iteration'])
    evaluations = [read(str(p.relative_to(public))) for p in sorted((public / 'evaluations').glob('*/result.json'))]
    tasks = list(dict.fromkeys(t for e in evaluations for t in e['sampled_tasks']))
    if task is not None and task not in tasks:
        raise ValueError(f'Task {task!r} is absent from the recorded evaluation plans.')
    task = task or (tasks[0] if tasks else None)
    candidates = []
    assigned = {cid: checkpoint for checkpoint in checkpoints for cid in checkpoint['candidate_ids']}
    files = sorted((public / 'candidates').glob('*.py'))
    baseline = files[0].stem if files else None
    for path in files:
        cid = path.stem
        source = read(f'candidates/{cid}.py', text=True)
        metadata = read(f'candidates/{cid}.json')
        source_hash = digest(source.encode())
        if metadata['source_sha256'] != source_hash:
            raise ValueError(f'Candidate source hash mismatch: {cid}')
        batches = [e for e in evaluations if cid in e['candidate_ids']]
        if len(batches) > 1:
            raise ValueError(f'{cid} has multiple evaluations; only the current continuous protocol is supported.')
        evaluation = batches[0] if batches else None
        if evaluation and evaluation['sources'][cid]['sha256'] != source_hash:
            raise ValueError(f'Evaluation source hash mismatch: {cid}')
        checkpoint = assigned.get(cid)
        iteration = 0 if cid == baseline else checkpoint['iteration'] if checkpoint else len(checkpoints) + 1
        reference = None if cid == baseline else (checkpoint['previous_incumbent'] if checkpoint
                    else checkpoints[-1]['incumbent'] if checkpoints else baseline)
        rows = [r for r in evaluation['runs'] if r['candidate_id'] == cid] if evaluation else []
        attempted = [r for r in rows if r['status'] != 'not_started']
        def total(key):
            values = [r.get('agent_usage', {}).get(key) for r in attempted]
            return sum(values) if values and all(v is not None for v in values) else None
        selected_run = next((r for r in rows if r['task_id'] == task), None)
        path_data = None
        trace_path = None
        if selected_run:
            trace_path = f'evaluations/{evaluation["evaluation_id"]}/{selected_run["directory"]}/trace.json'
            trace = read(trace_path, optional=True)
            if trace is not None:
                path_data = execution_patterns(trace)
        scored = sum(r.get('verification_verdict') in ('pass', 'fail') for r in rows)
        candidates.append(dict(
            id=cid, iteration=iteration, checkpoint=checkpoint, reference=reference,
            source=source, source_sha256=source_hash, rationale=metadata['rationale'],
            evaluation_id=evaluation['evaluation_id'] if evaluation else None,
            evaluation_status=evaluation['status'] if evaluation else 'not_evaluated',
            feedback_ready=bool(evaluation and evaluation.get('feedback_ready')),
            passed=sum(r.get('verification_verdict') == 'pass' for r in rows),
            scored=scored, planned=len(rows), attempted=len(attempted),
            missing=sum(r.get('verification_verdict') not in ('pass', 'fail') for r in attempted),
            statuses=dict(Counter(r['status'] for r in rows)),
            agent_input_tokens=total('model_input_tokens'), agent_model_calls=total('model_calls'),
            tasks=[dict(task_id=r['task_id'], status=r['status'], verdict=r.get('verification_verdict'),
                        jev_status=r.get('jev', {}).get('status', 'not_recorded')) for r in rows],
            execution=path_data, trace_path=trace_path))
    candidates.sort(key=lambda c: (c['iteration'], c['id']))
    return dict(as_of=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                source=str(public), task=task, progress=progress, checkpoints=checkpoints,
                candidates=candidates, provenance=provenance)


def label(value):
    return escape(str(value))


def number(value):
    return f'{value:,}' if value is not None else 'Unknown'


def render_execution(execution, reference):
    if execution is None:
        return '<p class="empty">No trace recorded for this task yet.</p>'
    previous = {str(name) for p in (reference or {}).get('patterns', []) for name, _ in p['sequence']}
    # Merge observed sequences into a display spine. This aligns recorded calls;
    # the edges below are counted from recordings, never implied by spine order.
    sequences = [[(str(name), status) for name, status in p['sequence']] for p in execution['patterns']]
    spine = []
    for sequence in sequences:
        merged = []
        for op, a, b, x, y in difflib.SequenceMatcher(a=spine, b=sequence, autojunk=False).get_opcodes():
            if op in ('equal', 'delete', 'replace'):
                merged.extend(spine[a:b])
            if op in ('insert', 'replace'):
                merged.extend(sequence[x:y])
        spine = merged
    positions = []
    edges = Counter()
    for sequence, pattern in zip(sequences, execution['patterns']):
        cursor, indices = 0, []
        for call in sequence:
            cursor = spine.index(call, cursor)
            indices.append(cursor)
            cursor += 1
        positions.append(indices)
        for pair in zip(indices, indices[1:]):
            edges[pair] += len(pattern['occurrences'])
    last = None
    for row in execution['order']:
        indices = positions[row['pattern']]
        if last is not None:
            edges[last, indices[0]] += 1
        if row['repeat'] > 1:
            edges[indices[-1], indices[0]] += row['repeat'] - 1
        last = indices[-1]
    skips = [(a, b) for a, b in edges if b != a + 1]
    lanes = {edge: i for i, edge in enumerate(skips)}
    margin = 28 + 14 * len(skips)
    center, top, bottom = margin + 24, margin, margin + 48
    width, height = max(180, len(spine) * 154 + 6), margin * 2 + 48
    graph = [f'<div class="graph-scroll" tabindex="0" role="region" aria-label="Horizontal execution path">'
             f'<svg class="execution-graph" style="max-width:{width}px;min-width:{width * .85:.0f}px" viewBox="0 0 {width} {height}" role="img" aria-label="Observed component transitions from left to right; edge labels count recorded transitions">']
    for (a, b), count in edges.items():
        xa, xb = 74 + a * 154, 74 + b * 154
        if b == a + 1:
            path = f'M{xa+62} {center}H{xb-62}'
            arrow = f'M{xb-66} {center-3}L{xb-62} {center}L{xb-66} {center+3}'
            tx, ty = (xa + xb) / 2, center - 7
        else:
            backwards = b <= a
            edge = bottom if backwards else top
            lane = edge + (1 if backwards else -1) * (14 + lanes[a, b] * 14)
            path = f'M{xa} {edge}V{lane}H{xb}V{edge}'
            tip = edge + (4 if backwards else -4)
            arrow = f'M{xb-3} {tip}L{xb} {edge}L{xb+3} {tip}'
            tx, ty = (xa + xb) / 2, lane - 5
        graph.append(f'<path class="graph-edge" d="{path}"/><path class="graph-edge" d="{arrow}"/>'
                     f'<text class="edge-count" x="{tx}" y="{ty}">{count}</text>')
    for i, (name, status) in enumerate(spine):
        changed = reference is not None and name not in previous
        classes = 'graph-node' + (' added' if changed else '') + (' incomplete' if status != 'completed' else '')
        x = 12 + i * 154
        graph.append(f'<g class="{classes}"><rect x="{x}" y="{top}" width="124" height="48" rx="2"/>'
                     f'<text x="{x+62}" y="{center+4}">{label(name)}</text>'
                     f'<title>{label(name)} · {label(status)}</title></g>')
    graph.append('</svg></div>')
    blocks = []
    for i, pattern in enumerate(execution['patterns']):
        nodes = []
        for name, status in pattern['sequence']:
            changed = reference is not None and str(name) not in previous
            classes = 'node' + (' added' if changed else '') + (' incomplete' if status != 'completed' else '')
            nodes.append(f'<li class="{classes}"><span>{label(name)}</span>'
                         + (f'<small>{label(status)}</small>' if status != 'completed' else '') + '</li>')
        blocks.append(f'<div class="pattern"><header><b>P{i+1}</b><span>× {len(pattern["occurrences"])}</span></header>'
                      f'<ol class="path">{"".join(nodes)}</ol></div>')
    order = ' <span class="arrow">→</span> '.join(
        f'P{r["pattern"]+1}' + (f' × {r["repeat"]}' if r['repeat'] > 1 else '') for r in execution['order'])
    return (''.join(graph) + f'<p class="trace-state">Trace: {label(execution["trace_status"])}. Numbers count observed transitions.</p>'
            + '<details><summary>Exact path order</summary><div class="patterns">' + ''.join(blocks) + '</div>'
            + f'<p class="path-order">{order or "No component invocations yet."}</p></details>')


def render_report(data):
    indexed = {c['id']: c for c in data['candidates']}
    cards = []
    for c in data['candidates']:
        previous = indexed.get(c['reference'])
        stage = 'Baseline' if c['iteration'] == 0 else f'Round {c["iteration"]:02d}'
        current = c['id'] == data['progress'].get('incumbent')
        checkpoint = c['checkpoint']
        selected = checkpoint and checkpoint['incumbent'] == c['id']
        status = ('Current best' if current else 'Starting point' if c['iteration'] == 0 else 'Selected this round' if selected else
                  'Not selected' if checkpoint else 'Evaluated' if c['feedback_ready'] else
                  c['evaluation_status'].replace('_', ' '))
        if not c['planned']:
            score, score_note = '—', 'Awaiting evaluation'
        else:
            score = f'{c["passed"]}<small>/{c["scored"]}</small>'
            score_note = f'{c["scored"]} of {c["planned"]} tasks scored'
        # The full rationale stays available verbatim; no model-generated summary.
        excerpt = c['rationale'][:320]
        if len(c['rationale']) > 320:
            excerpt = excerpt.rsplit(' ', 1)[0] + '…'
        diff = ''.join(difflib.unified_diff(previous['source'].splitlines(keepends=True),
                                           c['source'].splitlines(keepends=True),
                                           fromfile=previous['id'], tofile=c['id'])) if previous else ''
        comparison = f'Compared with round-start incumbent {label(previous["id"])}' if previous else 'Host-supplied starting point'
        task_rows = ''.join(f'<tr><td>{label(t["task_id"])}</td><td>{label(t["verdict"] or "Not scored")}</td>'
                            f'<td>{label(t["status"])}</td><td>{label(t["jev_status"])}</td></tr>' for t in c['tasks'])
        counts = Counter(str(name) for p in (c['execution'] or {}).get('patterns', [])
                         for occurrence in p['occurrences'] for name, _ in p['sequence'])
        invocation_counts = ', '.join(f'{label(name)} × {count}' for name, count in counts.items()) or 'No recorded calls for the displayed task.'
        comparable = (previous and c['feedback_ready'] and previous['feedback_ready']
                      and [t['task_id'] for t in c['tasks']] == [t['task_id'] for t in previous['tasks']])
        if comparable:
            difference = c['passed'] - previous['passed']
            observed = f'{difference:+d} passed tasks versus {previous["id"]}.'
            before, after = previous['agent_input_tokens'], c['agent_input_tokens']
            if before and after is not None:
                observed += f' Agent input changed by {(after / before - 1) * 100:+.1f}%.'
        elif c['feedback_ready']:
            observed = f'{c["passed"]} of {c["scored"]} tasks passed in the recorded evaluation.'
        else:
            observed = f'{c["scored"]} of {c["planned"]} tasks scored. Complete evaluation feedback is not available yet.' if c['planned'] else 'Evaluation has not started.'
        dots = ''.join(f'<span class="task-dot {label(t["verdict"] or "pending")}" title="{label(t["task_id"])}: {label(t["verdict"] or t["status"])}">'
                       + ('●' if t['verdict'] == 'pass' else '×' if t['verdict'] == 'fail' else '·') + '</span>' for t in c['tasks'])
        cards.append(f'''<article class="candidate{' selected' if current else ''}">
<header class="candidate-head"><div class="candidate-identity"><span class="eyebrow">{stage}</span><h2>{label(c['id'])}</h2><p>{comparison}</p></div><div class="evaluation">
<div class="score-row"><strong>{score}</strong><span>{label(status)}</span></div>{f'<p class="score-note">{score_note}</p>' if not c['feedback_ready'] else ''}<div class="task-dots">{dots}</div>
<dl class="cost"><div><dt>Agent input tokens</dt><dd>{number(c['agent_input_tokens'])}</dd></div><div><dt>Model attempts</dt><dd>{number(c['agent_model_calls'])}</dd></div></dl></div></header>
<section class="path-section">{render_execution(c['execution'], previous['execution'] if previous else None)}</section>
<section class="description"><div><h3>Hypothesis <small>researcher rationale</small></h3><p>{label(excerpt)}</p>
<details><summary>Full rationale</summary><pre>{label(c['rationale'])}</pre></details></div><div><h3>Observed <small>evaluation results</small></h3><p>{label(observed)}</p>
<details><summary>Invocation counts · displayed task</summary><p class="observed-counts">{invocation_counts}</p></details></div></section>
<div class="candidate-details"><details><summary>Python source</summary><pre>{label(c['source'])}</pre></details>
{f'<details><summary>Source changes</summary><pre>{label(diff or "No source difference.")}</pre></details>' if previous else ''}
<details><summary>Task outcomes</summary><div class="table-scroll"><table><thead><tr><th>Task</th><th>Official score</th><th>Execution</th><th>Jev</th></tr></thead><tbody>{task_rows}</tbody></table></div></details></div></article>''')
    rail = []
    for checkpoint in data['checkpoints']:
        rail.append(f'<li><span>Round {checkpoint["iteration"]:02d}</span><b>{label(checkpoint["incumbent"])}</b></li>')
    notes = ''.join(f'<details><summary>Round {c["iteration"]:02d} · researcher notes</summary><pre>{label(c["notes"])}</pre></details>' for c in data['checkpoints'])
    facts = json.dumps(data, indent=2, ensure_ascii=False)
    values = {
        '__TITLE__': label(Path(data['source']).parents[1].name), '__DATE__': label(data['as_of']),
        '__STATUS__': label(data['progress']['status']), '__TASK__': label(data['task'] or 'Not recorded yet'),
        '__RAIL__': ''.join(rail) or '<li>No completed checkpoints yet.</li>',
        '__CARDS__': ''.join(cards) or '<p class="empty">No saved candidates yet.</p>',
        '__NOTES__': notes, '__FACTS__': label(facts),
    }
    return re.sub(r'__[A-Z_]+__', lambda match: values[match[0]], PAGE_TEMPLATE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path, help='Campaign, research, or research/public directory')
    parser.add_argument('--output', type=Path, required=True, help='Standalone HTML outside the campaign directory')
    parser.add_argument('--task', help='Task whose actual paths appear in every candidate card; defaults to the first frozen task')
    args = parser.parse_args()
    try:
        public, protected = public_directory(args.campaign)
        output = args.output.resolve()
        if output.is_relative_to(protected):
            raise ValueError('Write the visualization outside the campaign directory to preserve frozen evidence.')
        if output.suffix.lower() != '.html':
            raise ValueError('--output must name an HTML file.')
        data = read_campaign(public, args.task)
        atomic_text(output, render_report(data))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f'Cannot visualize this campaign: {error}\n')
    print(f'Wrote {output} ({len(data["candidates"])} candidates; task {data["task"]}).')


PAGE_TEMPLATE = r'''
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>LoopBlox research · __TITLE__</title>
<style>
:root { color-scheme:dark; --bg:#0d1511; --panel:#15231b; --line:#344c3e; --text:#e4ece5; --muted:#a4b7aa; --green:#8bd7b0; --amber:#efc484; --mono:ui-monospace,SFMono-Regular,Consolas,monospace; font:16px/1.6 Georgia,serif; color:var(--text); background:var(--bg); }
* { box-sizing:border-box; }
body { margin:0; }
main { max-width:1500px; padding:48px 32px 80px; margin:auto; }
h1,h2,h3,p { margin:0; }
h1 { font-size:clamp(32px,5vw,56px); line-height:1.1; font-weight:400; letter-spacing:-1px; margin:15px 0; }
h2 { font:25px var(--mono); }
h3 { font-size:19px; font-weight:400; margin-bottom:12px; }
h3 small { display:block; font:11px/1.6 var(--mono); color:var(--muted); margin-top:5px; }
p { color:var(--muted); }
.eyebrow { font:11px/1.5 var(--mono); letter-spacing:1.2px; text-transform:uppercase; color:var(--green); }
.intro { max-width:820px; font-size:19px; }
.meta { display:flex; flex-wrap:wrap; gap:8px 28px; margin:28px 0; border-block:1px solid var(--line); padding:12px 0; font:12px/1.7 var(--mono); color:var(--muted); overflow-wrap:anywhere; }
.rail { display:flex; flex-wrap:wrap; gap:0; list-style:none; padding:0; margin:14px 0 30px; }
.rail li { padding:8px 22px 8px 0; margin-right:22px; border-right:1px solid var(--line); font:12px/1.7 var(--mono); }
.rail li span,.rail li b { display:block; }
.rail li span { color:var(--muted); }
.rail li b { color:var(--green); }
.legend { font:12px/1.7 var(--mono); max-width:1050px; margin-bottom:24px; }
.legend strong { color:var(--amber); font-weight:400; }
.cards { display:grid; gap:24px; }
.candidate { min-width:0; background:var(--panel); border:1px solid var(--line); }
.candidate.selected { border-color:var(--green); }
.candidate-head { display:grid; grid-template-columns:minmax(200px,1fr) minmax(450px,1fr); gap:24px; padding:22px 26px; border-bottom:1px solid var(--line); align-items:center; }
.candidate-head h2 { margin:8px 0; }
.candidate-head p { font:11px/1.6 var(--mono); }
.evaluation { display:grid; grid-template-columns:1fr 1fr; gap:8px 30px; align-items:center; }
.score-row { display:flex; align-items:center; gap:18px; }
.score-row strong { font:36px var(--mono); }
.score-row small { font-size:19px; color:var(--muted); }
.score-row>span { font:11px/1.5 var(--mono); color:var(--muted); text-transform:uppercase; }
.selected .score-row>span,.selected .score-row strong { color:var(--green); }
.score-note { grid-column:1; font:11px var(--mono); }
.cost { grid-column:2; grid-row:1 / span 3; font:12px/1.8 var(--mono); margin:0; }
.cost div { display:flex; justify-content:space-between; gap:10px; }
.cost dt { color:var(--muted); }
.cost dd { margin:0; }
.task-dots { display:flex; gap:5px; flex-wrap:wrap; grid-column:1; }
.task-dot { display:flex; align-items:center; justify-content:center; width:14px; height:14px; border:1px solid #856a59; color:#d5a493; font:11px var(--mono); }
.task-dot.pass { border-color:#527e65; color:var(--green); font-size:7px; }
.task-dot.pending { color:var(--muted); border-color:var(--line); }
.path-section { padding:16px 26px 8px; }
.graph-scroll { overflow-x:auto; padding:6px 0; }
.graph-scroll:focus-visible,summary:focus-visible { outline:2px solid var(--green); outline-offset:3px; }
.execution-graph { display:block; width:100%; height:auto; margin:0; }
.graph-edge { fill:none; stroke:#6b8f79; stroke-width:1.1; }
.edge-count { font:10px var(--mono); text-anchor:middle; fill:var(--muted); paint-order:stroke; stroke:#15231b; stroke-width:4px; }
.graph-node rect { fill:#203127; stroke:#4d6657; }
.graph-node text { font:11px var(--mono); fill:var(--text); text-anchor:middle; }
.graph-node.added rect { fill:#302b20; stroke:var(--amber); }
.graph-node.added text { fill:var(--amber); }
.graph-node.incomplete rect { stroke-dasharray:4 3; }
.trace-state { font:10px/1.6 var(--mono); margin:10px 0; }
.patterns { display:grid; gap:10px; margin:14px 0; }
.pattern { min-width:0; border:1px solid var(--line); background:#101b15; padding:12px; display:grid; grid-template-columns:60px minmax(0,1fr); gap:12px; align-items:center; }
.pattern header { color:var(--muted); font:11px/1.8 var(--mono); }
.pattern header span { display:block; }
.pattern header b { color:var(--green); font-weight:400; }
.path { display:flex; gap:22px; list-style:none; margin:0; padding:0; overflow-x:auto; }
.node { position:relative; flex:0 0 130px; min-height:36px; border:1px solid #4d6657; background:#203127; padding:8px 4px; text-align:center; font:10px/1.5 var(--mono); overflow-wrap:anywhere; }
.node+.node:before { content:'→'; position:absolute; left:-19px; top:8px; color:var(--muted); }
.node.added { border-color:var(--amber); background:#302b20; color:var(--amber); }
.node.incomplete { border-style:dashed; }
.node small { display:block; color:var(--amber); font:9px/1.5 var(--mono); }
.path-order { font:11px/1.8 var(--mono); overflow-wrap:anywhere; margin-top:14px; }
.arrow { color:var(--green); }
.description { display:grid; grid-template-columns:1fr 1fr; gap:30px; padding:22px 26px; border-top:1px solid var(--line); }
.description>div { min-width:0; }
.description p { line-height:1.6; font-size:15px; margin-bottom:15px; }
.description .observed-counts { font:11px/1.8 var(--mono); overflow-wrap:anywhere; margin-top:12px; }
.candidate-details { padding:0 26px 14px; }
details { border-top:1px solid var(--line); padding:10px 0; }
summary { cursor:pointer; color:var(--green); font:12px/1.6 var(--mono); }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font:11px/1.7 var(--mono); background:#0f1a13; padding:14px; max-height:560px; overflow:auto; color:var(--muted); }
.table-scroll { overflow:auto; }
table { border-collapse:collapse; font:11px/1.6 var(--mono); width:100%; }
th,td { padding:8px; text-align:left; border-bottom:1px solid var(--line); white-space:nowrap; }
th { color:var(--muted); }
.notes { margin-top:32px; }
.notes h2 { font:25px Georgia,serif; margin-bottom:15px; }
.footnote { font:12px/1.8 var(--mono); margin:30px 0; color:var(--muted); }
.empty { padding:20px; font:12px/1.8 var(--mono); }
footer { margin-top:30px; border-top:1px solid var(--line); padding-top:18px; font:11px var(--mono); color:var(--muted); }
@media(max-width:900px) { .candidate-head { grid-template-columns:1fr; gap:18px; } }
@media(max-width:600px) { main { padding:28px 16px 50px; } .candidate-head,.description { padding:18px 16px; } .path-section { padding:10px 16px; } .candidate-details { padding:0 16px 12px; } .description { grid-template-columns:1fr; gap:18px; } .evaluation { grid-template-columns:1fr; } .cost { grid-row:auto; grid-column:1; margin-top:8px; } .meta { font-size:11px; } }
</style>
<main>
<header><span class="eyebrow">LoopBlox / research visualization</span><h1>Watch the Loop evolve.</h1><p class="intro">Saved candidates, recorded execution paths, and the evidence behind each selection.</p></header>
<div class="meta"><span>__TITLE__</span><span>Campaign: __STATUS__</span><span>Snapshot: __DATE__</span><span>Path example: __TASK__</span></div>
<section aria-label="Incumbent history"><span class="eyebrow">Best Loop at each completed round</span><ol class="rail">__RAIL__</ol></section>
<p class="legend">Each card diagrams recorded transitions on the same task. <strong>Amber marks components absent from the comparison trace.</strong> Lines show observed routes, with transition counts; they do not infer source-code conditions. Exact path order is available below each diagram.</p>
<div class="cards">__CARDS__</div>
<p class="footnote">Scores and costs cover each candidate’s recorded evaluation; diagrams and invocation counts cover only the displayed task. Agent costs exclude simulated users, post-run Jev and researcher usage. Unknown usage stays unknown. Incomplete batches cannot establish a new best Loop. Selection comes from host records. Researcher hypotheses and notes are claims; invocation counts and differences between runs do not establish causality. Recovery attempts are outside these per-candidate totals.</p>
<section class="notes"><h2>Research notes</h2>__NOTES__</section>
<details><summary>Snapshot data and source hashes</summary><pre>__FACTS__</pre></details>
<footer>Read-only local report · regenerate to update · no model calls or task execution</footer>
</main>
</html>
'''


if __name__ == '__main__':
    main()
