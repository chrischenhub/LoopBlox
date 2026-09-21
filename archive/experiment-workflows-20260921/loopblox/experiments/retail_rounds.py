"""One retail Loop lineage: three official train batches, then all official test."""

import argparse
import json
from pathlib import Path
import shutil
import sys

from loopblox import ROOT, snapshot_implementation
from loopblox.benchmarks.run_tau2 import compare, comparison_calls, user_client
from loopblox.benchmarks.tau2 import DEFAULT_TASK_LIMITS, Tau2Runner, load_suite
from loopblox.experiments.common import read, run_stage, verify
from loopblox.experiments.inheritance import episode, prepare_resume
from loopblox.experiments.study import BASELINE_CONTROLLER, model_settings, native_researcher_usage
from loopblox.research.session import ResearchSession
from loopblox.runtime.controller import model_usage
from loopblox.runtime.io import atomic_json, atomic_text, digest, image_id
from loopblox.runtime.model import ChatCompletionsClient


class RoundResearchSession(ResearchSession):
    """Require complete incumbent comparisons and evidence for replacing it."""

    def __init__(self, *, candidate_limit, **arguments):
        super().__init__(**arguments)
        self.candidate_limit = candidate_limit

    def save_candidate(self, arguments, timeout):
        if hasattr(self, 'candidate_limit'):
            duplicate = any(self.source(cid) == arguments.get('source') for cid in self.state['candidates'])
            if not duplicate and len(self.state['candidates']) - len(self.initial_candidates) >= self.candidate_limit:
                self.reject('The round candidate cap is reached. Finish with an evaluated candidate or retain the incumbent.')
        return super().save_candidate(arguments, timeout)

    def evaluate(self, arguments, timeout):
        if self.state['evaluations']:
            ids = arguments.get('candidate_ids')
            if (not isinstance(ids, list) or ids[:len(self.initial_candidates)] != self.initial_candidates
                    or len(ids) != len(self.initial_candidates) + 1):
                self.reject('Evaluate [baseline, incumbent, candidate], omitting duplicate IDs, on the full batch.')
        return super().evaluate(arguments, timeout)

    def finish(self, arguments, timeout):
        candidate = arguments.get('candidate_id')
        for evaluation in reversed(self.state['evaluations']):
            if candidate not in evaluation['candidate_ids'] or self.starting_candidate not in evaluation['candidate_ids']:
                continue
            if (len(evaluation['sampled_tasks']) != len(self.development)
                    or any(row.get('verification_verdict') not in {'pass', 'fail'} for row in evaluation['runs'])):
                continue

            def score(cid):
                rows = [row for row in evaluation['runs'] if row['candidate_id'] == cid]
                return (sum(row['verification_verdict'] == 'pass' for row in rows),
                        -sum(row['usage']['model_calls'] for row in rows))

            if candidate == self.starting_candidate or score(candidate) > score(self.starting_candidate):
                return super().finish(arguments, timeout)
            self.reject('Replacement must improve paired passes, or tie passes with fewer model calls. Otherwise retain the incumbent.')
        self.reject('Finish requires a complete scored batch including the submitted source and incumbent.')


def prepare(args):
    manifest = load_suite(args.suite)
    development = [task for task in manifest['tasks'] if task['split'] == 'development']
    holdout = [task for task in manifest['tasks'] if task['split'] == 'holdout']
    splits = read(Path(args.suite) / 'upstream/data/tau2/domains/retail/split_tasks.json')
    if ([task['upstream_id'] for task in development] != splits['train'][:30]
            or [task['upstream_id'] for task in holdout] != splits['test']
            or any(task['family'] != 'retail' for task in manifest['tasks'])):
        raise ValueError('Require exactly official retail train[:30] and all official test in their original order')
    if args.candidates < 1:
        raise ValueError('The per-round candidate cap must be positive')
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(args.suite, root / 'suite')
    initial = Path(args.initial_source).read_text()
    compile(initial, 'initial-loop.py', 'exec')
    atomic_text(root / 'initial-loop.py', initial)
    client = ChatCompletionsClient.from_env()
    user = user_client(argparse.Namespace(user_model=None, user_output_allowance=2048), client)
    limits = DEFAULT_TASK_LIMITS
    worker = image_id(args.worker_image)
    Tau2Runner(root / 'suite', manifest, client, user, worker, limits, root / 'private/preflight')
    task_cap = 20 + args.candidates * 30
    budgets = dict(task_runs=task_cap, seconds=task_cap * limits.seconds + 600,
                   model_calls=task_cap * limits.model_calls + 128,
                   output_tokens=task_cap * limits.output_tokens + 131072)
    experiment = read(ROOT / 'experiments/tau2.json')
    experiment['question'] = (
        'Improve the inherited retail Loop on this round\'s ten official training tasks. Only this batch can be '
        'executed; earlier rounds\' public training evidence is available as experience. Future batches and all test '
        'feedback are unavailable. The opening comparison measures baseline and incumbent before research starts. '
        f'Save at most {args.candidates} new candidates; early finish is allowed. For each candidate, evaluate '
        '[baseline, incumbent, candidate] (omit duplicate IDs), n=10, repeats=1. Read the current component contracts '
        'and evidence before proposing changes. Keep customer IDs, task answers, research history and domain-specific '
        'workflows out of source. Submit only after a complete paired evaluation. Replace the incumbent only with '
        'more passes, or equal passes and fewer total model calls; retain the incumbent on a full tie. If a candidate '
        'loses, use the remaining candidate allowance for another hypothesis or finish with the incumbent. Reserve '
        'budget for finish; do not request additional evaluations after the task allowance is used. These scores '
        'measure training performance, not established generalization. Component behavior and prompts remain frozen.')
    episodes = []
    for index in range(3):
        label = f'round-{index + 1:02d}'
        episodes.append(dict(label=label, directory=label, round=index + 1, condition='loop_memory',
            parent=f'round-{index:02d}' if index else None, seed=args.seed + index,
            task_ids=[task['task_id'] for task in development[index * 10:(index + 1) * 10]],
            session_options=dict(fixed_task_batch=True, opening_n=10, candidate_limit=args.candidates)))
    protocol = dict(mode='retail_official_rounds', conditions=['loop_memory'], rounds=3, episodes=episodes,
        research_budgets=budgets, concurrency=1, model=model_settings(client), user_model=model_settings(user),
        grader_model=model_settings(user), worker_image=worker, task_limits=vars(limits),
        task_ids=[task['task_id'] for task in development], holdout_task_ids=[task['task_id'] for task in holdout],
        experiment=experiment, baseline_sha256=digest(BASELINE_CONTROLLER.read_bytes()),
        initial_source=dict(path='initial-loop.py', sha256=digest(initial.encode()), origin=str(Path(args.initial_source).resolve())),
        suite_manifest_sha256=digest((root / 'suite/manifest.json').read_bytes()),
        implementation_sha256=snapshot_implementation(root), comparison_directory='final-test',
        max_research_runs=task_cap * 3, max_training_check_runs=0, max_test_runs=len(holdout) * 3,
        design='One source-and-experience lineage, initialized from the user-selected loop08 submission. Three '
               'rounds expose official train[:10], train[10:20], train[20:30] in file order. Each researcher executes '
               'only its ten current tasks. The opening full batch closes before the researcher receives feedback. '
               'Only completed episodes in this campaign export experience; no old pilot traces are inherited. '
               'All researchers close before final baseline/L0/L3 evaluation on every official test task, one trial '
               'per source/task with rotated source order. Identical sources share rows with explicit aliases. '
               'Old pilot sources and prior test exposure prevent a claim that this entire test set was unseen. '
               'All official IDs are retained, including NL grading, handoffs, related families and weak-score cases. '
               'The configured user model also grades official NL assertions, replacing the upstream default grader '
               'model; official grader prompts and reward rules remain unchanged. Report this custom configuration. '
               'Every task, researcher, user and grader attempt is charged; failures and missing scores remain visible. '
               f'Task time is {limits.seconds} seconds excluding recognized API timeout attempts and their retry waits. '
               'The same waits are excluded from research time; successful requests count toward time. '
               'Wall time, excluded waits and charged time remain separately recorded; calls and tokens are not refunded.')
    atomic_json(root / 'protocol.json', protocol)
    atomic_json(root / 'result.json', dict(status='prepared', episodes=[{**item, 'status': 'not_started'} for item in episodes]))
    report(root)
    print(json.dumps(dict(output=str(root), research_task_cap=task_cap * 3, test_task_cap=len(holdout) * 3)), flush=True)


def check(root):
    protocol = verify(root)
    if any(read(root / item['directory'] / 'result.json')['status'] != 'complete' for item in protocol['episodes']):
        raise ValueError('Every researcher must submit and close before test evaluation')
    closures = {item['label']: digest((root / item['directory'] / 'private/state.json').read_bytes())
                for item in protocol['episodes']}
    final = root / protocol['episodes'][-1]['directory'] / 'selected-controller.py'
    result = read(final.parent / 'result.json')
    if digest(final.read_bytes()) != result['selected_sha256']:
        raise ValueError('Final submitted source changed')
    initial = root / protocol['initial_source']['path']
    if digest(initial.read_bytes()) != protocol['initial_source']['sha256']:
        raise ValueError('Initial source changed')
    aliases, additional = {'baseline': 'baseline'}, []
    identities = {protocol['baseline_sha256']: 'baseline'}
    for name, path in (('initial', initial), ('final', final)):
        sha = digest(path.read_bytes())
        if sha not in identities:
            identities[sha] = name
            additional.append((name, path))
        aliases[name] = identities[sha]
    atomic_json(root / 'check-plan.json', dict(aliases=aliases, research_state_hashes=closures,
                task_ids=protocol['holdout_task_ids'], repeats=1))
    args = argparse.Namespace(suite=root / 'suite', output=root / 'final-test', worker_image=protocol['worker_image'],
        repeats=1, development_per_domain=None, user_model=protocol['user_model']['model'],
        user_output_allowance=protocol['user_model']['max_tokens'],
        **{'task_' + key: value for key, value in protocol['task_limits'].items()})
    previous = root / 'final-test/private/prior-check'
    compare(args, controllers=additional, split='holdout', previous=previous if previous.exists() else None)
    for item in protocol['episodes']:
        if digest((root / item['directory'] / 'private/state.json').read_bytes()) != closures[item['label']]:
            raise ValueError('Research changed during final test evaluation')


def run(root):
    verify(root)
    state = read(root / 'result.json')
    if state['status'] != 'prepared':
        raise ValueError('Use a new recovery directory for an interrupted campaign')
    try:
        state['status'] = 'researching'
        for item in state['episodes']:
            if item['status'] == 'complete':
                continue
            item['status'] = 'running'
            atomic_json(root / 'result.json', state)
            code = run_stage([sys.executable, '-P', '-B', '-m', __spec__.name, 'episode', str(root), item['label']])
            path = root / item['directory'] / 'result.json'
            item['status'] = 'complete' if code == 0 and path.exists() and read(path)['status'] == 'complete' else 'interrupted'
            atomic_json(root / 'result.json', state)
            report(root)
            if item['status'] != 'complete':
                raise RuntimeError('Stopped after unsuccessful ' + item['label'])
        state['status'] = 'testing'
        atomic_json(root / 'result.json', state)
        code = run_stage([sys.executable, '-P', '-B', '-m', __spec__.name, 'check', str(root)])
        state['status'] = 'complete' if code == 0 else 'interrupted'
    except BaseException as error:
        state.update(status='interrupted', error_type=type(error).__name__, error=str(error))
        for item in state['episodes']:
            if item['status'] == 'running':
                item['status'] = 'interrupted'
        raise
    finally:
        atomic_json(root / 'result.json', state)
        report(root)


def report(root):
    protocol, state = read(root / 'protocol.json'), read(root / 'result.json')
    calls, rounds, attempts, scored, native_records = [], [], 0, 0, []
    for item in state['episodes']:
        directories = [root / old['directory'] for old in item.get('prior_attempts', [])] + [root / item['directory']]
        for directory in directories:
            ledger = directory / 'private/research-usage.json'
            if ledger.exists():
                calls.extend(read(ledger)['calls'])
            native = native_researcher_usage(directory)
            if native is not None:
                native_records.append(dict(directory=str(directory.relative_to(root)), usage=native))
            path = directory / 'private/state.json'
            if path.exists():
                episode_state = read(path)
                attempts += episode_state['task_runs_used']
                scored += sum(row.get('verification_verdict') in {'pass', 'fail'}
                              for evaluation in episode_state['evaluations'] for row in evaluation['runs'])
        path = root / item['directory'] / 'private/state.json'
        current = read(path) if path.exists() else {}
        rounds.append(dict(label=item['label'], status=item['status'], selected=current.get('frozen_candidate'),
                           task_runs=current.get('task_runs_used', 0)))
    comparison = root / 'final-test/result.json'
    if not comparison.exists():
        comparison = root / 'final-test/private/prior-check/result.json'
    test = read(comparison) if comparison.exists() else {}
    test_rows = test.get('comparisons', [])
    test_attempts = sum(row['status'] != 'not_started' for row in test_rows)
    test_scored = sum(row.get('verification_verdict') in {'pass', 'fail'} for row in test_rows)
    test_calls = comparison_calls(root / 'final-test')
    summary = dict(status=state['status'], rounds=rounds, training_attempts=attempts, training_scored=scored,
        test_attempts=test_attempts, test_scored=test_scored, missing_scores=attempts + test_attempts - scored - test_scored,
        training_usage=model_usage(calls), test_usage=model_usage(test_calls), total_usage=model_usage(calls + test_calls),
        native_researcher_usage=native_records)
    atomic_json(root / 'analysis.json', summary)
    lines = ['# Retail: three training batches and all official test', '', f"Status: **{state['status']}**.", '',
             '| Round | Status | New attempts | Selected |', '| --- | --- | ---: | --- |']
    lines += [f"| {item['label']} | {item['status']} | {item['task_runs']} | {item['selected']} |" for item in rounds]
    lines += ['', f'Training: {attempts} attempts, {scored} scored. Test: {test_attempts} attempts, {test_scored} scored.',
              f"Host gateway model attempts: {summary['total_usage']['model_calls']}; missing task scores: {summary['missing_scores']}.",
              'Native researcher tokens are recorded separately in analysis.json; native provider attempt counts '
              'and subscription prices remain unknown.',
              '', protocol['design'], '', '[Protocol](protocol.json) · [Accounting](analysis.json) · [Test comparison](final-test/report.html)', '']
    atomic_text(root / 'report.md', '\n'.join(lines))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'episode', 'check', 'report', 'resume'))
    parser.add_argument('output', type=Path)
    parser.add_argument('label', nargs='?')
    parser.add_argument('--suite', type=Path)
    parser.add_argument('--initial-source', type=Path)
    parser.add_argument('--candidates', type=int, default=2)
    parser.add_argument('--seed', type=int, default=20260915)
    parser.add_argument('--worker-image', default='python:3.12-slim')
    parser.add_argument('--from-campaign', type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    if args.command == 'prepare':
        if args.suite is None or args.initial_source is None:
            parser.error('prepare requires --suite and --initial-source')
        prepare(args)
    elif args.command == 'episode':
        episode(root, args.label, session_type=RoundResearchSession)
    elif args.command == 'resume':
        if args.from_campaign is None:
            parser.error('resume requires --from-campaign')
        prepare_resume(args.from_campaign, root, reporter=report)
    else:
        {'run': run, 'check': check, 'report': report}[args.command](root)
        if args.command == 'run' and read(root / 'result.json')['status'] != 'complete':
            raise SystemExit(1)


if __name__ == '__main__':
    main()
