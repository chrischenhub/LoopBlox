"""Frozen random screening followed by serial, bounded ResearchSession branches."""

import argparse
import json
import math
from pathlib import Path
import shutil
import sys
import time

from loopblox import ROOT, snapshot_implementation
from loopblox.research.session import ResearchSession, export_experience, research_evidence
from loopblox.runtime.controller import Limits, ModelMeter, model_usage
from loopblox.runtime.model import ChatCompletionsClient
from loopblox.research.sampling import generate_candidates
from loopblox.experiments.common import clients, run_stage, verify
from loopblox.benchmarks.run_tau2 import user_client
from loopblox.runtime.io import atomic_json, atomic_text, digest, image_id
from loopblox.experiments.study import BASELINE_CONTROLLER, model_settings
from loopblox.benchmarks.tau2 import Tau2Runner, load_suite





def read(path):
    return json.loads(Path(path).read_text())


def prepare(args):
    manifest = load_suite(args.suite)
    if not manifest['tasks'] or any(t['split'] != 'development' for t in manifest['tasks']):
        raise ValueError('Use a development-only suite; this pilot does not run holdout')
    if args.count < args.top or min(args.top, args.batch, args.deep_runs) < 1:
        raise ValueError('Require count >= top and positive batch/deep-run budgets')
    experiment = read(ROOT / 'experiments/tau2.json')
    candidates = generate_candidates(experiment['exposed'], args.count, args.seed)
    client = ChatCompletionsClient.from_env()
    user = user_client(argparse.Namespace(user_model=None, user_output_allowance=2048), client)
    worker = image_id(args.worker_image)
    limits = Limits(seconds=300, actions=40, model_calls=64, output_tokens=65536)
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(args.suite, root / 'suite')
    Tau2Runner(root / 'suite', manifest, client, user, worker, limits, root / 'private/preflight')
    entries = []
    for index, candidate in enumerate(candidates, 1):
        name = f'loop{index:02d}'
        source_path = f'candidates/{name}.py'
        atomic_text(root / source_path, candidate['source'])
        entries.append(dict(name=name, source=source_path, sha256=digest(candidate['source'].encode()),
                            **{key: candidate[key] for key in ('sampling', 'attempt', 'rationale')}))
    screening_runs = 1 + (args.count + 1) * args.batch
    deep_runs = 2 + args.deep_runs
    protocol = dict(
        model=model_settings(client), user_model=model_settings(user), worker_image=worker,
        task_limits=vars(limits), task_ids=[t['task_id'] for t in manifest['tasks']],
        holdout_task_ids=[], experiment=experiment, seed=args.seed, batch=args.batch, top=args.top,
        candidates=entries, baseline_sha256=digest(BASELINE_CONTROLLER.read_bytes()),
        suite_manifest_sha256=digest((root / 'suite/manifest.json').read_bytes()),
        implementation_sha256=snapshot_implementation(root),
        screening_budgets=dict(task_runs=screening_runs, seconds=screening_runs * limits.seconds,
                               model_calls=screening_runs * limits.model_calls,
                               output_tokens=screening_runs * limits.output_tokens),
        research_budgets=dict(task_runs=deep_runs, seconds=5400,
                              model_calls=deep_runs * limits.model_calls + 128,
                              output_tokens=deep_runs * limits.output_tokens + 128 * client.max_tokens),
        ranking='Fully scored candidates: descending passes, ascending model calls, input tokens, '
                'output tokens, then frozen generation order. Baseline is a separate reference.',
        design='Ten (or configured count) source-frozen random candidates share a complete development batch '
               'with the unified baseline. Uniform sampling with replacement follows ResearchSession; '
               'repeated draws do not add independent task groups. An opening baseline trial is charged separately. '
               'The top candidates start fresh, serial researchers with equal budgets and source-only inheritance. '
               'Each branch has its own baseline/start opening pair, then the specified additional development '
               'allowance. Screening evidence is not exported as completed research experience. '
               'No validation or holdout is run, and branch scores from different batches do not establish a final winner.')
    atomic_json(root / 'protocol.json', protocol)
    atomic_json(root / 'result.json', dict(status='prepared', branches=[], top=[]))
    report(root)
    print(json.dumps(dict(output=str(root), random_candidates=args.count, screening_runs=screening_runs,
                          branches=args.top, max_runs_per_branch=deep_runs)), flush=True)
    return root


def prepare_dfs(args):
    """Start a new study from completed Top 3 submissions without rerunning screening."""
    source, root = Path(args.name).resolve(), args.output.resolve()
    old, previous = read(source / 'protocol.json'), read(source / 'result.json')
    if (not previous.get('branches') or any(item['status'] != 'complete' for item in previous['branches'])
            or args.nodes < 1 or args.depth < 1 or args.batch < 1):
        raise ValueError('DFS requires completed starting branches and positive node/depth limits')
    if root.is_relative_to(source):
        raise ValueError('New DFS study must be outside the historical campaign')
    client, user = clients(old)
    worker = image_id(old['worker_image'])
    manifest = load_suite(source / 'suite')
    if any(task['split'] != 'development' for task in manifest['tasks']):
        raise ValueError('DFS pilot uses only development tasks')
    if digest(BASELINE_CONTROLLER.read_bytes()) != old['baseline_sha256']:
        raise ValueError('Keep the same unified baseline')
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / 'suite', root / 'suite')
    Tau2Runner(root / 'suite', manifest, client, user, worker,
               Limits(**old['task_limits']), root / 'private/preflight')
    candidates = []
    for item in previous['branches']:
        name = item['name']
        episode = source / 'branches' / name
        selected = episode / 'selected-controller.py'
        submitted = read(episode / 'result.json')
        if digest(selected.read_bytes()) != submitted['selected_sha256']:
            raise ValueError('Submitted source changed: ' + name)
        path = f'candidates/{name}.py'
        atomic_text(root / path, selected.read_text())
        export_experience(episode, root / 'experience' / name)
        candidates.append(dict(name=name, source=path, sha256=submitted['selected_sha256'],
            starting_reference=f'{source.name}/branches/{name}/{submitted["selected"]}',
            experience=f'experience/{name}'))
    runs = 2 + 2 * args.batch * args.nodes + 2 * args.batch
    policy = dict(nodes=args.nodes, depth=args.depth, width=2, batch=args.batch)
    protocol = {key: old[key] for key in ('model', 'user_model', 'worker_image', 'task_limits',
                'task_ids', 'holdout_task_ids', 'experiment', 'baseline_sha256', 'suite_manifest_sha256')}
    protocol.update(mode='dfs', seed=args.seed, batch=args.batch, top=len(candidates), candidates=candidates,
        dfs=policy, source_campaign=str(source),
        research_budgets=dict(task_runs=runs, seconds=max(5400, runs * 150),
            model_calls=runs * old['task_limits']['model_calls'] + 256,
            output_tokens=runs * old['task_limits']['output_tokens'] + 256 * client.max_tokens),
        inherited_files={str(path.relative_to(root)): digest(path.read_bytes())
                         for path in (root / 'experience').rglob('*') if path.is_file()},
        design='New development-only depth-first study from explicitly completed Top 3 submissions and their '
               'own public evidence. The host records parent-child edges, explores children before siblings, '
               'and backtracks at the frozen depth limit or exhausted child slots. Full paired batches precede expansion; '
               'scores never automatically prune descendants. Exploration and final selection are separate. '
               'Node count is a maximum, not a novelty quota; explicit early finish remains possible and is '
               'reported as reduced coverage. Reserve one full baseline comparison before submission. '
               'No validation, holdout or across-branch winner claim. Old study costs are provenance, not '
               'new-study spend. Recovery retains failed attempts privately and subtracts their spend.')
    protocol['implementation_sha256'] = snapshot_implementation(root)
    atomic_json(root / 'protocol.json', protocol)
    atomic_json(root / 'result.json', dict(status='prepared', top=[item['name'] for item in candidates],
        branches=[dict(name=item['name'], status='not_started') for item in candidates]))
    report(root)
    print(json.dumps(dict(output=str(root), dfs=policy, max_runs_per_branch=runs,
                          max_new_task_runs=runs * len(candidates))), flush=True)
    return root


def screening_calls(root):
    prior = root / 'private/prior-campaign'
    calls = screening_calls(prior) if prior.exists() else []
    ledger = root / 'screening/private/research-usage.json'
    reused = read(root / 'protocol.json').get('recovery', {}).get('screening_reused', False)
    return calls + (read(ledger)['calls'] if ledger.exists() and not reused else [])


def branch_spend(folder):
    state, result = read(folder / 'private/state.json'), read(folder / 'result.json')
    usage = model_usage(read(folder / 'private/research-usage.json')['calls'])
    return dict(task_runs=state['task_runs_used'], model_calls=usage['model_calls'],
                output_tokens=usage['charged_output_tokens'], seconds=math.ceil(result['elapsed_seconds']))


def branch_budget(root, protocol, name):
    prior = protocol.get('recovery', {}).get('prior_branches', {}).get(name, [])
    spent = [branch_spend(root / path) for path in prior]
    return {key: cap - sum(item[key] for item in spent)
            for key, cap in protocol['research_budgets'].items()}


def prepare_resume(source, root):
    """Preserve settled screening and submissions; restart unfinished researchers."""
    source = Path(source).resolve()
    if root.resolve().is_relative_to(source):
        raise ValueError('Recovery output must be outside the preserved campaign')
    protocol, state = read(source / 'protocol.json'), read(source / 'result.json')
    if state['status'] != 'interrupted':
        raise ValueError('Recovery requires a stopped campaign')
    for path, expected in protocol.get('inherited_files', {}).items():
        if digest((source / path).read_bytes()) != expected:
            raise ValueError('Inherited public evidence changed: ' + path)
    implementation_changes = {}
    for name, expected in protocol['implementation_sha256'].items():
        if digest((source / 'implementation' / name).read_bytes()) != expected:
            raise ValueError('Original frozen implementation changed: ' + name)
        current = digest((ROOT / name).read_bytes())
        if name not in {'loopblox/runtime/model.py', 'loopblox/runtime/controller.py', 'loopblox/research/session.py',
                        'controllers/research.py', 'loopblox/experiments/search.py', 'AGENTS.md', 'README.md'}:
            if current != expected:
                raise ValueError('Recovery must retain the library, environment and instructions: ' + name)
        if current != expected:
            implementation_changes[name] = dict(previous_sha256=expected, sha256=current)
    for entry in protocol['candidates']:
        if digest((source / entry['source']).read_bytes()) != entry['sha256']:
            raise ValueError('Original random source changed: ' + entry['name'])
    manifest = load_suite(source / 'suite')
    if digest((source / 'suite/manifest.json').read_bytes()) != protocol['suite_manifest_sha256']:
        raise ValueError('Original task manifest changed')
    dfs = protocol.get('mode') == 'dfs'
    old = read(source / 'screening/private/state.json') if not dfs else dict(evaluations=[], task_runs_used=0)
    rows = [row for evaluation in old['evaluations'] for row in evaluation['runs']]
    if not dfs and (len(old['evaluations']) != 2 or any(row['status'] == 'running' for row in rows)
            or old['evaluations'][0]['summary']['candidates']['c0000']['unscored']):
        raise ValueError('Recovery requires a scored opening and a settled shared screening plan')
    used = sum(row['status'] != 'not_started' for row in rows)
    if used != old['task_runs_used']:
        raise ValueError('Screening row and task accounting disagree')
    usage = model_usage(screening_calls(source))
    result = read(source / 'screening/result.json') if not dfs else dict(dispatch_complete=True, elapsed_seconds=0)
    screening_reused = result.get('dispatch_complete', False)
    seconds = result.get('elapsed_seconds')
    if seconds is None:
        seconds = ((source / 'screening/result.json').stat().st_mtime
                   - (source / 'screening/private/setup.json').stat().st_mtime)
    spent = dict(task_runs=used, model_calls=usage['model_calls'],
                 output_tokens=usage['charged_output_tokens'], seconds=math.ceil(max(0, seconds)))
    remaining = {key: cap - spent[key] for key, cap in protocol.get('screening_budgets', {}).items()}
    if not screening_reused and (any(value <= 0 for key, value in remaining.items() if key != 'task_runs')
            or remaining['task_runs'] < sum(r['status'] == 'not_started' for r in rows)):
        raise ValueError('Remaining screening caps cannot admit the unstarted rows')
    client, user = clients(protocol)
    image_id(protocol['worker_image'])
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source, root / 'private/prior-campaign')
    shutil.copytree(source / 'suite', root / 'suite')
    shutil.copytree(source / 'candidates', root / 'candidates')
    if dfs:
        shutil.copytree(source / 'experience', root / 'experience')
    Tau2Runner(root / 'suite', manifest, client, user, protocol['worker_image'],
               Limits(**protocol['task_limits']), root / 'private/preflight')
    preserved = [root / 'private/prior-campaign']
    if screening_reused and not dfs:
        shutil.copytree(source / 'screening', root / 'screening')
        preserved.append(root / 'screening')
    elif not screening_reused and state.get('branches'):
        raise ValueError('Research branches require closed screening')
    prior_branches = {name: ['private/prior-campaign/' + path for path in paths]
                      for name, paths in protocol.get('recovery', {}).get('prior_branches', {}).items()}
    branches = []
    for item in state.get('branches', []):
        name = item['name']
        folder = source / 'branches' / name
        if item['status'] == 'complete':
            submitted, saved = read(folder / 'result.json'), read(folder / 'private/state.json')
            if (saved.get('research_status') != 'completed' or not saved.get('selection_reason')
                    or digest((folder / 'selected-controller.py').read_bytes()) != submitted['selected_sha256']):
                raise ValueError('Only explicitly submitted research may be reused: ' + name)
            shutil.copytree(folder, root / 'branches' / name)
            preserved.append(root / 'branches' / name)
            branches.append(item)
        else:
            if (folder / 'private/state.json').exists():
                prior_branches.setdefault(name, []).append('private/prior-campaign/branches/' + name)
            branches.append(dict(name=name, status='not_started'))
    protocol['implementation_sha256'] = snapshot_implementation(root)
    protocol['recovery'] = dict(source_campaign=str(source), spent=spent, remaining=remaining,
        screening_reused=screening_reused, prior_branches=prior_branches,
        implementation_changes=implementation_changes,
        imported_files={str(path.relative_to(root)): digest(path.read_bytes())
                        for folder in preserved for path in folder.rglob('*') if path.is_file()},
        policy='Recovery in a new process and campaign. Closed screening and submitted branches are exact '
               'snapshots. Unfinished screening runs only unstarted rows; missing scores stay missing. '
               'Interrupted branches start fresh researchers from their original selected root sources, '
               'without importing failed research as experience. Prior task/model/charged-output/time spend '
               'is subtracted from each original cap; completed branches and old attempts are counted once. '
               'Provider startup notices may trigger user-authorized scheduled recovery after 14 minutes.')
    for item in branches:
        if item['status'] != 'complete':
            budget = branch_budget(root, protocol, item['name'])
            if min(budget.values()) <= 0 or budget['task_runs'] < 2:
                raise ValueError('No fresh opening comparison fits the remaining branch cap: ' + item['name'])
    atomic_json(root / 'protocol.json', protocol)
    atomic_json(root / 'result.json', dict(status='prepared', branches=branches, top=state.get('top', [])))
    report(root)
    print(json.dumps(dict(output=str(root), prior_task_runs=used, remaining=remaining)), flush=True)
    return root


def session_for(root, protocol, label, budget, starting=None):
    for path, expected in protocol.get('inherited_files', {}).items():
        if digest((root / path).read_bytes()) != expected:
            raise ValueError('Inherited public evidence changed: ' + path)
    client, user = clients(protocol)
    limits = Limits(**protocol['task_limits'])
    runner = Tau2Runner(root / 'suite', load_suite(root / 'suite'), client, user,
                       protocol['worker_image'], limits, root / 'private/environments' / label)
    experiment = dict(protocol['experiment'])
    dfs = protocol.get('mode') == 'dfs'
    if dfs:
        experiment['question'] += (
            f" This explicitly requested study uses depth-first search from {starting['starting_reference']}. "
            f"The frozen DFS policy is {json.dumps(protocol['dfs'])}. Read dfs.json for the current frontier. "
            "For each child, read and modify the indicated parent's Python source; supply that parent_id to "
            "save_candidate. Use a meaningful behavioral change, not formatting, comments or a wholesale reset "
            "to an unrelated ancestor. Explain the delta and hypothesis in the rationale. Inspect existing "
            "public evidence and exact component contracts before designing. Literal API mistakes are rejected "
            "before task dispatch; this check cannot validate all dynamic paths. "
            f"Evaluate [parent_id, child_id] together with n={protocol['batch']}. Complete that full comparison "
            "before saving the next child. The host then advances depth-first and backtracks; do not choose "
            "a sibling until it is the indicated frontier. A score tie or decrease does not prevent exploring "
            "the child's descendants. Try complementary follow-up mechanisms, including repairs, without "
            "assuming that a poor intermediate design must be the final submission. Selection remains independent. "
            f"You have at most {budget['task_runs']} total task attempts including the opening pair. Aim to "
            f"explore up to {protocol['dfs']['nodes']} children and reach depth {protocol['dfs']['depth']} "
            "while preserving the budget for a final full-batch baseline comparison. A root scoring 5/5, a "
            "single unsuccessful child, or unfamiliarity with a component is not by itself a reason to stop. "
            "If further search is unjustified or cannot fit, early submission is allowed: explain which "
            "directions remain unexplored. Before finish, evaluate [baseline_candidate, proposed_submission] "
            f"on a fresh n={protocol['batch']} batch (only baseline if selecting baseline itself). "
            "Submit the strongest supported evaluated candidate, which need not be the current frontier. "
            "Report success and cost uncertainty; do not claim a causal gain from noisy development draws.")
    elif starting:
        experiment['question'] += (
            f" This branch starts from {starting['name']}, selected by the host's random-loop screening. "
            f"Use the supplied starting source as your initial line of investigation. You have "
            f"{budget['task_runs'] - 2} development task runs after the baseline/start opening pair. "
            f"Evaluate proposed changes with a parent and child sharing n={protocol['batch']} draws, "
            "then use that evidence for the next revision. Do not reject a design from the first task alone. "
            "Read the relevant public execution evidence and distinguish observations from hypotheses. "
            "The initial generator's templates do not constrain subsequent Python changes. "
            "Submit an evaluated candidate with finish while sufficient researcher budget remains. "
            "You may retain the starting Loop or baseline if your results justify that selection.")
    session_class = ResearchSession
    options = {}
    if dfs:
        from loopblox.research.dfs import DFSResearchSession
        session_class = DFSResearchSession
        options = dict(dfs_policy=protocol['dfs'], experience=root / starting['experience'])
    return session_class(
        output=root / label, development=tuple(protocol['task_ids']), holdout=(), run_task=runner,
        research_client=client, worker_image=protocol['worker_image'],
        setup=dict(model=protocol['model'], user_model=protocol['user_model'],
                   campaign_protocol_sha256=digest((root / 'protocol.json').read_bytes()),
                   starting_reference=None if not starting else starting.get('starting_reference', f"screening/{starting['name']}")),
        experiment=experiment, baseline_source=BASELINE_CONTROLLER.read_text(),
        starting_source=None if not starting else (root / starting['source']).read_text(),
        max_task_runs=budget['task_runs'], research_seconds=budget['seconds'],
        research_model_calls=budget['model_calls'], research_output_tokens=budget['output_tokens'],
        task_limits=limits, seed=protocol['seed'] + (1 if starting else 0), **options)


def screen(root):
    protocol = verify(root)
    for entry in protocol['candidates']:
        if digest((root / entry['source']).read_bytes()) != entry['sha256']:
            raise ValueError('Frozen random source changed: ' + entry['name'])
    recovery = protocol.get('recovery')
    budget = dict(protocol['screening_budgets'])
    if recovery:
        budget.update({key: value for key, value in recovery['remaining'].items() if key != 'task_runs'})
    session = session_for(root, protocol, 'screening', budget)
    entries = []
    for entry in protocol['candidates']:
        saved = session.save_candidate(dict(source=(root / entry['source']).read_text(), rationale=entry['rationale']), 0)
        entries.append({**entry, 'candidate_id': saved['candidate_id']})
    session.meter = ModelMeter(session.private / 'research-usage.json', **session.budgets)
    session.state['status'] = 'researching'
    session.save()
    result = dict(status='running', method='Host screening; no researcher process or research submission',
                  candidates=entries, ranking=[], top=[])
    started = time.monotonic()
    try:
        if recovery:
            prior = root / 'private/prior-campaign/screening'
            old = read(prior / 'private/state.json')
            if old['candidates'] != session.state['candidates']:
                raise ValueError('Candidate identities differ from the frozen screening')
            shutil.copytree(prior / 'public/evaluations', session.public / 'evaluations', dirs_exist_ok=True)
            session.state.update(evaluations=old['evaluations'], task_runs_used=old['task_runs_used'])
            session.save()
            feedback = session.run_evaluation(session.state['evaluations'][1])
        else:
            session.evaluate(dict(candidate_ids=session.initial_candidates, n=1), 0)
            feedback = session.evaluate(dict(candidate_ids=session.initial_candidates + [e['candidate_id'] for e in entries],
                                             n=protocol['batch']), 0)
        if any(row['status'] == 'not_started' for row in feedback['runs']):
            raise RuntimeError('Screening budget ended before all planned rows were attempted')
        scores = feedback['summary']['candidates']
        for entry in entries:
            entry['score'] = scores[entry['candidate_id']]
        eligible = [e for e in entries if e['score']['attempted'] == protocol['batch']
                    and e['score']['unscored'] == 0]
        def key(entry):
            score, usage = entry['score'], entry['score']['usage']
            return (-score['resolved'], *(usage[k] if usage[k] is not None else float('inf')
                     for k in ('model_calls', 'model_input_tokens', 'model_output_tokens')), entry['name'])
        ranking = sorted(eligible, key=key)
        if len(ranking) < protocol['top']:
            raise RuntimeError('Fewer than the requested number of fully scored candidates')
        excluded = [entry for entry in entries if entry not in eligible]
        result.update(status='incomplete' if excluded else 'complete', dispatch_complete=True,
                      excluded=excluded, ranking=ranking, top=ranking[:protocol['top']],
                      baseline=scores[session.initial_candidates[0]],
                      evaluation=feedback['artifact'], draws=[r['task_id'] for r in feedback['runs']
                                                           if r['candidate_id'] == session.initial_candidates[0]])
        session.select(dict(candidate_id=ranking[0]['candidate_id']), 0)
        session.state.update(status='selected', frozen_candidate=ranking[0]['candidate_id'])
        atomic_text(session.output / 'selected-controller.py', session.source(ranking[0]['candidate_id']))
    except BaseException as error:
        result.update(status='interrupted', error_type=type(error).__name__, error=str(error))
        session.state['status'] = 'interrupted'
        raise
    finally:
        session.save()
        result.update(task_runs=session.state['task_runs_used'], usage=model_usage(screening_calls(root)),
                      elapsed_seconds=time.monotonic() - started + (recovery['spent']['seconds'] if recovery else 0))
        atomic_json(session.output / 'result.json', result)


def branch(root, name):
    protocol = verify(root)
    entries = protocol['candidates'] if protocol.get('mode') == 'dfs' else read(root / 'screening/result.json')['top']
    starting = next(e for e in entries if e['name'] == name)
    if digest((root / starting['source']).read_bytes()) != starting['sha256']:
        raise ValueError('Starting source changed')
    session = session_for(root, protocol, 'branches/' + name, branch_budget(root, protocol, name), starting)
    result = dict(status='running', name=name, starting_reference=starting.get('starting_reference', f'screening/{name}'))
    atomic_json(session.output / 'result.json', result)
    started = time.monotonic()
    try:
        session.research()
        if session.state.get('research_status') != 'completed' or not session.state.get('selection_reason'):
            raise RuntimeError('Research stopped without an explicit completed submission')
        result.update(status='complete', selected=session.state['frozen_candidate'],
                      selected_sha256=digest((session.output / 'selected-controller.py').read_bytes()),
                      selection_reason=session.state['selection_reason'])
    except BaseException as error:
        result.update(status='interrupted', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        result.update(task_runs=session.state['task_runs_used'], evidence=research_evidence(session.state),
                      elapsed_seconds=time.monotonic() - started)
        if hasattr(session, 'meter'):
            result['usage'] = session.meter.summary()
        atomic_json(session.output / 'result.json', result)


def run(root):
    protocol = verify(root)
    state = read(root / 'result.json')
    if state['status'] != 'prepared':
        raise ValueError('Run requires a fresh prepared campaign; interrupted work is not automatically retried')
    try:
        dfs = protocol.get('mode') == 'dfs'
        if not dfs and not protocol.get('recovery', {}).get('screening_reused'):
            state['status'] = 'screening'
            atomic_json(root / 'result.json', state)
            if run_stage([sys.executable, '-P', '-B', '-m', 'loopblox.experiments.search', 'screen', str(root)]):
                raise RuntimeError('Screening stopped; later work was not dispatched')
        screening = read(root / 'screening/result.json') if not dfs else dict(status='complete', top=protocol['candidates'])
        state.update(status='researching', top=[e['name'] for e in screening['top']],
                     branches=state.get('branches') or [dict(name=e['name'], status='not_started') for e in screening['top']])
        atomic_json(root / 'result.json', state)
        report(root)
        for item in state['branches']:
            if item['status'] == 'complete':
                continue
            item['status'] = 'running'
            atomic_json(root / 'result.json', state)
            print('Deepening ' + item['name'], flush=True)
            exit_code = run_stage([sys.executable, '-P', '-B', '-m', 'loopblox.experiments.search', 'branch', str(root), item['name']])
            item.update(read(root / 'branches' / item['name'] / 'result.json'))
            atomic_json(root / 'result.json', state)
            report(root)
            if exit_code or item['status'] != 'complete':
                raise RuntimeError('A research branch stopped; later branches were not dispatched')
        state['status'] = screening['status']
    except BaseException as error:
        state.update(status='interrupted', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        atomic_json(root / 'result.json', state)
        report(root)


def report(root):
    protocol, state = read(root / 'protocol.json'), read(root / 'result.json')
    dfs = protocol.get('mode') == 'dfs'
    lines = ['# Top 3 depth-first search' if dfs else '# Random Loop screening and Top 3 research', '', f"Status: **{state['status']}**", '',
             'Development-only pilot. All scores are search evidence; no validation or holdout gain is established.', '',
             f"Seed: {protocol['seed']}. Starting candidates: {len(protocol['candidates'])}. "
             f"Shared batch draws: {protocol['batch']}. Branches: {protocol['top']}.", '']
    if dfs:
        lines += [protocol['design'], '', f"DFS limits: {protocol['dfs']}. Per-branch caps: {protocol['research_budgets']}.", '',
                  '## Frozen starting submissions', '', '| Loop | Submitted source |', '|---|---|']
    else:
        lines += ['## Frozen candidates', '', '| Loop | Context | Decision | Observation | Extra behavior |',
                  '|---|---|---|---|---|']
    for entry in protocol['candidates']:
        if dfs:
            lines.append(f"| [{entry['name']}]({entry['source']}) | {entry['starting_reference']} |")
            continue
        sample = entry['sampling']
        extras = [f"{key}={sample[key]}" for key in ('opening_analysis', 'turn_analysis', 'recovery',
                  'action_review', 'completion_review') if sample[key]]
        lines.append(f"| [{entry['name']}]({entry['source']}) | {sample['context']} | "
                     f"{sample['decision']}/{sample['selection']} | {sample['observation']} | {'; '.join(extras) or 'none'} |")
    path = root / 'screening/result.json'
    if path.exists():
        screening = read(path)
        lines += ['', '## Screening', '', f"Status: {screening['status']}"]
        if screening.get('ranking'):
            lines += ['', '| Rank | Loop | Passes | Model calls | Input tokens |', '|---|---|---|---|---|']
        if 'baseline' in screening:
            base = screening['baseline']
            lines.append(f"| reference | baseline | {base['resolved']}/{base['attempted']} | "
                         f"{base['usage']['model_calls']} | {base['usage']['model_input_tokens']} |")
        for index, entry in enumerate(screening.get('ranking', []), 1):
            score = entry['score']
            lines.append(f"| {index} | [{entry['name']}]({entry['source']}) | {score['resolved']}/{score['attempted']} | "
                         f"{score['usage']['model_calls']} | {score['usage']['model_input_tokens']} |")
        for entry in screening.get('excluded', []):
            score = entry['score']
            lines += ['', f"Excluded from ranking: {entry['name']}; {score['resolved']} pass, "
                      f"{score['unresolved']} fail, {score['unscored']} unscored. The prior failure is retained."]
        if not screening.get('ranking'):
            saved = read(root / 'screening/private/state.json')
            batch = next((e for e in saved['evaluations'] if len(e['candidate_ids']) > 1), None)
            if batch:
                screening['draws'] = batch['sampled_tasks']
                # This is a view of preallocated evaluation rows, never a partial ranking.
                lines += ['', 'Incomplete batch; no Top N has been selected.', '',
                          '| Loop | Pass | Fail | Unscored attempts | Not started |',
                          '|---|---|---|---|---|']
                names = {e['candidate_id']: e['name'] for e in screening['candidates']}
                for candidate in batch['candidate_ids']:
                    rows = [row for row in batch['runs'] if row['candidate_id'] == candidate]
                    passed = sum(row.get('verification_verdict') == 'pass' for row in rows)
                    failed = sum(row.get('verification_verdict') == 'fail' for row in rows)
                    unscored = sum(row['status'] != 'not_started' and row.get('verification_verdict') is None for row in rows)
                    pending = sum(row['status'] == 'not_started' for row in rows)
                    lines.append(f"| {names.get(candidate, 'baseline')} | {passed} | {failed} | {unscored} | {pending} |")
                lines += ['', f"Canonical rows: [evaluation record](screening/public/evaluations/{batch['evaluation_id']}/result.json)."]
                faults = [row for row in batch['runs'] if row['status'] in ('host_fault', 'operational_failure', 'verifier_failure')]
                for row in faults:
                    lines += ['', f"Failure: {names.get(row['candidate_id'], 'baseline')} / {row['task_id']}: "
                              f"{row.get('stop_reason', row['status'])}. Elapsed: {row.get('elapsed_seconds')} seconds. "
                              'The missing score and reserved usage are retained.']
        lines += ['', f"Draws (repeats retained): {screening.get('draws', [])}"]
        if screening.get('error'):
            lines += ['', 'Stopped: ' + screening['error']]
    lines += ['', '## Research branches', '']
    lines += (['| Start | Status | Selected source | Task runs |', '|---|---|---|---|']
              if state.get('branches') else ['Not started.'])
    for item in state.get('branches', []):
        path = root / 'branches' / item['name'] / 'result.json'
        actual = read(path) if path.exists() else item
        source = f"[selected](branches/{item['name']}/selected-controller.py)" if actual['status'] == 'complete' else '—'
        prior = protocol.get('recovery', {}).get('prior_branches', {}).get(item['name'], [])
        old_runs = sum(branch_spend(root / path)['task_runs'] for path in prior)
        lines.append(f"| {item['name']} | {actual['status']} | {source} | {actual.get('task_runs', 0) + old_runs} |")
    if dfs:
        for item in state.get('branches', []):
            path = root / 'branches' / item['name'] / 'public/dfs.json'
            if not path.exists():
                continue
            tree = read(path)
            lines += ['', f"## {item['name']} search tree", '',
                      f"Completed edges: {tree['completed_edges']}/{protocol['dfs']['nodes']}. "
                      f"Next parent: {tree['next_parent_id']}. Pending: {tree['pending']}.", '',
                      '| Candidate | Parent | Paired evaluation |', '|---|---|---|']
            for node in tree['nodes']:
                prefix = f"branches/{item['name']}/public"
                evaluation = (f"[{node['evaluation_id']}]({prefix}/evaluations/{node['evaluation_id']}/result.json)"
                              if node['evaluation_id'] else '—')
                lines.append(f"| [{node['candidate_id']}]({prefix}/candidates/{node['candidate_id']}.py) | "
                             f"{node['parent_id'] or 'root'} | {evaluation} |")
    calls, task_runs = screening_calls(root), 0
    for paths in protocol.get('recovery', {}).get('prior_branches', {}).values():
        for path in paths:
            calls.extend(read(root / path / 'private/research-usage.json')['calls'])
            task_runs += branch_spend(root / path)['task_runs']
    for folder in [root / 'screening', *(root / 'branches').glob('*')]:
        ledger, episode_state = folder / 'private/research-usage.json', folder / 'private/state.json'
        if folder != root / 'screening' and ledger.exists():
            calls.extend(read(ledger)['calls'])
        if episode_state.exists():
            task_runs += read(episode_state)['task_runs_used']
    usage = model_usage(calls)
    if 'recovery' in protocol:
        if not (root / 'screening/private/state.json').exists():
            task_runs += protocol['recovery']['spent']['task_runs']
        lines += ['', '## Recovery', '', protocol['recovery']['policy'], '',
                  f"Prior screening spend: {protocol['recovery']['spent']}. "
                  f"Remaining screening caps: {protocol['recovery']['remaining']}.", '',
                  'Original campaign: [preserved report](private/prior-campaign/report.md).']
    lines += ['', f"Actual total: {task_runs} task runs; {usage['model_calls']} model requests. "
              'Researcher, task-agent and simulated-user calls are counted once from the episode ledgers.', '',
              'Branch selections are separate submissions, not a final paired comparison or holdout ranking.', '']
    atomic_json(root / 'analysis.json', dict(status=state['status'], task_runs=task_runs, usage=usage, holdout_runs=0))
    atomic_text(root / 'report.md', '\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'dfs', 'resume', 'run', 'screen', 'branch', 'report'))
    parser.add_argument('output', type=Path)
    parser.add_argument('name', nargs='?')
    parser.add_argument('--suite', type=Path)
    parser.add_argument('--worker-image', default='python:3.12-slim')
    parser.add_argument('--seed', type=int, default=20260913)
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--batch', type=int, default=5)
    parser.add_argument('--top', type=int, default=3)
    parser.add_argument('--deep-runs', type=int, default=20)
    parser.add_argument('--nodes', type=int, default=6)
    parser.add_argument('--depth', type=int, default=3)
    args = parser.parse_args()
    root = args.output.resolve()
    if args.command == 'prepare':
        prepare(args)
    elif args.command == 'dfs':
        prepare_dfs(args)
    elif args.command == 'resume':
        prepare_resume(args.name, root)
    elif args.command == 'run':
        run(root)
    elif args.command == 'screen':
        screen(root)
    elif args.command == 'branch':
        branch(root, args.name)
    else:
        report(root)


if __name__ == '__main__':
    main()
