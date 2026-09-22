"""Publish the reviewed first three iterations from explicit public research records."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path


# These explanations and drawings were reviewed against these exact Python sources.
# They are presentation, not an executable graph or inferred candidate genealogy.
STORIES = [
    dict(id='c0000', sha='81be84c534021b6c5bdd678e7a61518217d17e99eea51b8dd7bba2801a0a735e',
         title='Start with full history', change='The shared starting point',
         hypothesis='Read the full history, choose the next action, and retain its complete result.',
         observation='The reference result. Every candidate faces the same ten training tasks.'),
    dict(id='c0001', sha='476746b787263a88bd56f406770d75c1bd214030efa4c56ec2821ddc2ee58ad3',
         title='Reflect on repetition', change='+ A conditional Reflect',
         hypothesis='After two identical consecutive action requests, reflect once to help break repetition.'),
    dict(id='c0002', sha='74d1c3cea9e96cbfd6402279637835f5fd7d64b7ba1612ee3a9b26cd1d9570ce',
         title='Compress the history', change='+ A summary every 8 observations',
         hypothesis='Return to the baseline and periodically replace accumulated history with a summary.'),
    dict(id='c0003', sha='e99c96a20459f41ededcbaf836fbb4032919f581417bd95221c58a8cfbadaef3',
         title='Review after compression', change='+ Critique at summary boundaries',
         hypothesis='Review the first summary-driven decision against original history; revise once if unsupported.'),
]


def snapshot(public_root, target):
    """Read public records only. Never refresh or write to the running campaign."""
    public_root = Path(public_root).resolve()
    progress_path = public_root / 'progress.json'
    progress_raw = progress_path.read_bytes()
    progress = json.loads(progress_raw)
    records = []
    for i, story in enumerate(STORIES):
        cid = story['id']
        source_path = public_root / f'candidates/{cid}.py'
        source = source_path.read_text()
        source_sha = hashlib.sha256(source.encode()).hexdigest()
        if source_sha != story['sha']:
            raise ValueError(f'Review the {cid} illustration against the changed source first.')
        relative = f'evaluations/e{i:04d}/result.json'
        raw = (public_root / relative).read_bytes()
        result = json.loads(raw)
        if result['candidate_ids'] != [cid] or result['sources'][cid]['sha256'] != source_sha:
            raise ValueError(f'Evaluation/source mismatch for {cid}.')
        if not result['feedback_ready'] or result['status'] != 'completed':
            raise ValueError(f'{cid} does not have complete released feedback yet.')
        if i and result['sampled_tasks'] != records[0]['task_ids']:
            raise ValueError('The task lists differ.')
        runs = result['runs']
        if len(runs) != 10 or any(r['jev']['status'] != 'completed' for r in runs):
            raise ValueError(f'{cid} requires ten fully analyzed task runs.')
        checkpoint_path = public_root / f'checkpoints/iteration-{i:04d}.json'
        checkpoint_raw = checkpoint_path.read_bytes() if i and checkpoint_path.exists() else None
        checkpoint = json.loads(checkpoint_raw) if checkpoint_raw else None
        if checkpoint and checkpoint['candidate_ids'] != [cid]:
            raise ValueError(f'Review the iteration mapping for {cid}.')
        def total(key):
            values = [r['agent_usage'].get(key) for r in runs]
            return sum(values) if all(v is not None for v in values) else None
        counts = Counter()
        for run in runs:
            counts.update(run['jev']['summary']['component_invocations'])
        records.append(dict(
            id=cid, iteration=i, source=source, source_sha256=source_sha,
            rationale=json.loads((public_root / f'candidates/{cid}.json').read_text())['rationale'],
            evaluation=relative, evaluation_sha256=hashlib.sha256(raw).hexdigest(),
            task_ids=result['sampled_tasks'], passed=sum(r['verification_verdict'] == 'pass' for r in runs),
            failed=sum(r['verification_verdict'] == 'fail' for r in runs),
            missing=sum(r['verification_verdict'] not in ('pass', 'fail') for r in runs),
            statuses=dict(Counter(r['status'] for r in runs)),
            agent_input_tokens=total('model_input_tokens'), agent_model_calls=total('model_calls'),
            incomplete_usage_calls=total('incomplete_usage_calls'), component_invocations=dict(counts),
            tasks=[dict(task_id=r['task_id'], verdict=r['verification_verdict'], status=r['status'],
                        component_invocations=r['jev']['summary']['component_invocations']) for r in runs],
            checkpoint=(dict(path=f'checkpoints/{checkpoint_path.name}',
                             sha256=hashlib.sha256(checkpoint_raw).hexdigest(),
                             incumbent=checkpoint['incumbent'], previous_incumbent=checkpoint['previous_incumbent'])
                        if checkpoint else None)))
    if progress['incumbent'] not in [r['id'] for r in records]:
        raise ValueError('Research has advanced beyond this reviewed snapshot; review its scope first.')
    data = dict(campaign=public_root.parents[1].name,
                as_of=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                source_records=f'.artifacts/tau2/{public_root.parents[1].name}/research/public',
                progress_sha256=hashlib.sha256(progress_raw).hexdigest(),
                incumbent=progress['incumbent'], records=records)
    Path(target).write_text(json.dumps(data, indent=2) + '\n')


def diagram(index):
    """A reviewed source overview. Dotted boxes are conditional, not recorded calls."""
    parts = [f'<svg class="recipe" viewBox="0 0 248 432" role="img" aria-labelledby="recipe-{index}">',
             f'<title id="recipe-{index}">{html.escape(STORIES[index]["hypothesis"])}</title>',
             '<path class="recipe-wire" d="M124 52V374"/>']
    def box(y, label, detail='', changed=False, conditional=False):
        style = (' added' if changed else '') + (' conditional' if conditional else '')
        parts.append(f'<g class="recipe-node{style}"><rect x="30" y="{y}" width="188" height="44" rx="3"/>'
                     f'<text x="124" y="{y+19}">{label}</text>'
                     f'<text class="recipe-detail" x="124" y="{y+34}">{detail}</text></g>')
    box(12, 'Full context', 'full / summary + new history' if index >= 2 else 'all recorded history')
    if index == 1:
        box(85, 'Reflect + full context', 'only at 2 identical requests', True, True)
    elif index >= 2:
        box(85, 'Summarize → new base', 'every 8 observations', index == 2, True)
    if index:
        parts.append('<path class="recipe-bypass" d="M124 64H235V142H124"/><text class="recipe-skip" x="228" y="79">else</text>')
    box(158, 'Decide', 'propose actions or completion')
    if index == 3:
        box(231, 'Critique → maybe Decide', 'original history · after summary', True, True)
        parts.append('<path class="recipe-bypass" d="M124 212H235V287H124"/><text class="recipe-skip" x="228" y="227">else</text>')
    box(304, 'Execute', 'if the proposal contains actions')
    box(374, 'Observe full', 'record the complete result')
    for y in (76, 150, 222, 296, 365):
        parts.append(f'<path class="recipe-wire" d="M120 {y-4}L124 {y}L128 {y-4}"/>')
    parts.extend(['<path class="recipe-return" d="M30 396H12V34H27"/>',
                  '<path class="recipe-return" d="M23 30L28 34L23 38"/>', '</svg>'])
    return ''.join(parts)


def render(data):
    cards, rail = [], []
    incumbent = 'c0000'
    for i, (story, record) in enumerate(zip(STORIES, data['records'], strict=True)):
        cid = record['id']
        if cid != story['id'] or record['source_sha256'] != story['sha']:
            raise ValueError('Snapshot and reviewed diagrams disagree.')
        if hashlib.sha256(record['source'].encode()).hexdigest() != story['sha']:
            raise ValueError('Snapshot source hash mismatch.')
        checkpoint = record['checkpoint']
        if checkpoint:
            incumbent = checkpoint['incumbent']
        elif i:
            incumbent = data['incumbent']
        current = cid == data['incumbent']
        status = 'Starting point' if i == 0 else 'Selected' if current else 'Not selected'
        stage = 'Baseline' if i == 0 else f'Round {i:02d}'
        failures = record['failed']
        tokens = record['agent_input_tokens']
        token_label = 'Unknown' if tokens is None else f'{tokens / 1_000_000:.2f}M'
        baseline_tokens = data['records'][0]['agent_input_tokens']
        delta = 'reference' if i == 0 else 'unknown' if tokens is None else f'{(tokens / baseline_tokens - 1) * 100:+.1f}% vs baseline'
        counts = record['component_invocations']
        if i == 0:
            observation = story['observation']
        elif i == 1:
            failed_triggers = sum(r['component_invocations'].get('reflect', 0) for r in record['tasks'] if r['verdict'] == 'fail')
            observation = f'Reflect ran {counts.get("reflect", 0)} time in the batch; {failed_triggers} times on failed tasks.'
        elif i == 2:
            gain = record['passed'] - data['records'][0]['passed']
            observation = f'{gain} additional task passed versus baseline. Agent input changed by {(tokens / baseline_tokens - 1) * 100:+.1f}%.'
        else:
            observation = f'{counts.get("context_summary", 0)} summaries, {counts.get("critique", 0)} Critiques. Fewer tasks passed than in round 2.'
        classes = 'evolution-card selected' if current else 'evolution-card'
        cards.append(f'''<article class="{classes}">
          <header><span class="round-label">{stage} <span>{cid}</span></span>
          <h3>{story['title']}</h3><p class="change-label">{story['change']}</p></header>
          {diagram(i)}
          <p class="recipe-exit">Completion proposal → return{'; after review when triggered' if i == 3 else ''}.</p>
          <div class="candidate-result"><span class="score">{record['passed']}<small>/10</small></span><span class="selection-label">{status}</span></div>
          <div class="task-dots" aria-label="{record['passed']} passed, {failures} failed, {record['missing']} unscored">{''.join('<span class="task-dot '+r['verdict']+'" title="'+html.escape(r['task_id']+': '+r['verdict']+' ('+r['status']+')')+'">'+('●' if r['verdict']=='pass' else '×')+'</span>' for r in record['tasks'])}</div>
          <dl class="candidate-cost"><div><dt>Agent input</dt><dd>{token_label}</dd></div><div><dt>Model attempts</dt><dd>{record['agent_model_calls']}</dd></div></dl>
          <p class="cost-delta">{delta}</p>
          <div class="candidate-story"><span class="eyebrow">Hypothesis</span><p>{story['hypothesis']}</p><span class="eyebrow">Observed</span><p>{observation}</p></div>
          <footer><a href="sources/{cid}.py">Python ↗</a></footer>
        </article>''')
        score = next(r['passed'] for r in data['records'] if r['id'] == incumbent)
        rail.append(f'<li><span>{stage}</span><strong>{incumbent} <em>{score}/10</em></strong></li>')
    return {'__EVOLUTION_CARDS__': ''.join(cards), '__INCUMBENT_RAIL__': ''.join(rail),
            '__EVOLUTION_DATE__': html.escape(data['as_of'].replace('T', ' ').replace('+00:00', ' UTC')),
            '__EVOLUTION_CAMPAIGN__': html.escape(data['campaign'])}
