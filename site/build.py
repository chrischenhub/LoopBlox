"""Build the English LoopBlox introduction from reviewed copy and frozen sources."""
import argparse
import ast
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SNAPSHOTS = ROOT / 'snapshots'

# Plain-language names for a general audience. The catalog in loopblox/runtime/components.py owns the
# components; these labels are presentation only and are checked against it on every build.
PLAIN_NAMES = {
    'context_full': 'Full history',
    'context_recent': 'Recent executions',
    'context_summary': 'Summarized history',
    'observe_full': 'Full result',
    'observe_brief': 'Read a result page',
    'think': 'Analyze',
    'plan': 'Plan objectives',
    'decide': 'Decide next step',
    'choose': 'Compare proposals',
    'critique': 'Assess the evidence',
    'reflect': 'Diagnose a failure',
    'judge': 'Judge with Jev',
    'execute': 'Run the tools',
    'execute_rule': 'Run a fixed rule',
}


def build(refresh_notes=False):
    if refresh_notes:
        SNAPSHOTS.mkdir(exist_ok=True)
        for source, target in [('README.md', 'project.md'), ('loop.md', 'loop.md'),
                               ('controllers/reactive.py', 'reactive.py'),
                               ('docs/experiments/dfs-closeout-20260915/results.json', 'results.json'),
                               ('docs/experiments/dfs-closeout-20260915/README.md', 'experiment-report.md')]:
            shutil.copyfile(ROOT.parent / source, SNAPSHOTS / target)
        for args, target in [([], 'components.json'), (['--markdown'], 'component-contracts.md')]:
            result = subprocess.check_output([sys.executable, '-B', '-m', 'loopblox.runtime.components', *args], cwd=ROOT.parent)
            (SNAPSHOTS / target).write_bytes(result)

    catalog = json.loads((SNAPSHOTS / 'components.json').read_text())
    baseline = (SNAPSHOTS / 'reactive.py').read_text()
    calls = [node.args[0].value for node in ast.walk(ast.parse(baseline))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == 'component' and node.args and isinstance(node.args[0], ast.Constant)]
    # The illustration is a reviewed explanation of this supplied recipe, not a graph compiler.
    if calls != ['context_full', 'decide', 'execute', 'observe_full']:
        raise ValueError('The baseline changed; review its task-loop illustration before publishing.')

    missing = sorted(set(catalog) - set(PLAIN_NAMES))
    extra = sorted(set(PLAIN_NAMES) - set(catalog))
    if missing or extra:
        raise ValueError(f'Plain-language names are out of date; missing {missing}, unknown {extra}.')
    for name, spec in catalog.items():
        spec['plain'] = PLAIN_NAMES[name]

    families = {}
    for name, spec in catalog.items():
        family = spec['family']
        families.setdefault(family['id'], {'definition': family, 'members': []})['members'].append(name)
    groups = []
    for i, family in enumerate(families.values(), 1):
        definition = family['definition']
        members = ''.join('<li><button data-component="{0}" aria-pressed="false">'
                          '<span class="plain">{1}</span><span class="ident">{0}</span></button></li>'.format(
                              html.escape(name), html.escape(PLAIN_NAMES[name]))
                          for name in family['members'])
        groups.append(f'<section class="family"><span class="eyebrow">0{i} / {len(family["members"])} COMPONENTS</span>'
                      f'<h3>{html.escape(definition["label"])}</h3><p>{html.escape(definition["description"])}</p>'
                      f'<ul>{members}</ul></section>')
    results = json.loads((SNAPSHOTS / 'results.json').read_text())
    result_rows = []
    for branch in results['branches']:
        candidate, baseline_result = branch['candidate'], branch['baseline']
        status = 'Submitted' if branch['status'] == 'submitted' else 'No accepted submission'
        result_rows.append(
            f'<tr><th scope="row"><code>{html.escape(branch["name"])}</code>'
            f'<span>{html.escape(branch["description"])}</span></th>'
            f'<td class="result-score">{candidate["passed"]}/{candidate["attempts"]}</td>'
            f'<td class="result-score">{baseline_result["passed"]}/{baseline_result["attempts"]}</td>'
            f'<td class="result-calls">{candidate["model_calls"]} / {baseline_result["model_calls"]}</td>'
            f'<td>{status}</td></tr>')
    totals = results['cumulative_dfs']
    result_metrics = ''.join(
        f'<div><dt>{label}</dt><dd>{totals[key]:,}</dd></div>'
        for key, label in [('attempts', 'Task attempts'), ('scored', 'Scored results'),
                           ('missing_scores', 'Missing scores'), ('model_calls', 'Model attempts')])
    latest = results['latest_recovery']
    closeout = (f'All {latest["completed_scored_attempts"]} task attempts in the latest recovery received scores, '
                f'with {latest["new_missing_scores"]} new missing scores. '
                'After evaluation, a submission-guard error rejected the researcher’s baseline submission. '
                'The operator stopped the researcher; loop04 has no accepted submission. '
                'Earlier loop06 and loop08 submissions remain preserved.')
    digest = hashlib.sha256(''.join((SNAPSHOTS / name).read_text() for name in
                                    ['project.md', 'loop.md', 'components.json', 'reactive.py',
                                     'results.json', 'experiment-report.md']).encode()).hexdigest()
    template = (ROOT / 'index.html').read_text()
    for name in set(re.findall(r'data-component="([a-z_]+)"', template)):
        if name not in catalog:
            raise ValueError(f'Unknown displayed component: {name}')
    for marker, content in {
        '__STYLE__': (ROOT / 'assets/style.css').read_text(),
        '__APP__': (ROOT / 'assets/app.js').read_text(),
        '__DATA__': json.dumps(catalog, ensure_ascii=False).replace('</', '<\\/'),
        '__FAMILIES__': ''.join(groups),
        '__COMPONENT_COUNT__': str(len(catalog)),
        '__FAMILY_COUNT__': str(len(families)),
        '__BASELINE__': html.escape(baseline),
        '__SOURCE_DIGEST__': digest,
        '__RESULT_DATE__': html.escape(results['as_of']),
        '__RESULT_MODEL__': html.escape(results['model']),
        '__RESULT_ROWS__': ''.join(result_rows),
        '__RESULT_METRICS__': result_metrics,
        '__RESULT_CLOSEOUT__': closeout,
    }.items():
        if marker not in template:
            raise ValueError(f'Missing template marker: {marker}')
        template = template.replace(marker, content)

    output = ROOT / 'dist'
    if output.exists():
        shutil.rmtree(output)
    output.mkdir()
    (output / 'index.html').write_text(template)
    shutil.copytree(ROOT / 'assets/fonts', output / 'assets/fonts')
    shutil.copyfile(SNAPSHOTS / 'component-contracts.md', output / 'component-contracts.md')
    shutil.copyfile(SNAPSHOTS / 'reactive.py', output / 'baseline.py')
    shutil.copyfile(SNAPSHOTS / 'results.json', output / 'results.json')
    # The reviewed report's only other links point into repository documentation.
    report = (SNAPSHOTS / 'experiment-report.md').read_text()
    report = re.sub(r'\[([^\]]+)\]\((?!results\.json\))[^)]+\)', r'\1', report)
    (output / 'experiment-report.md').write_text(report)
    print(f'Built LoopBlox introduction with {len(catalog)} components in {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-notes', action='store_true',
                        help='Refresh project, concept, component and baseline snapshots from the parent repository')
    build(parser.parse_args().refresh_notes)
