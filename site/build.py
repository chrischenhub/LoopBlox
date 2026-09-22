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
from evolution import render as render_evolution, snapshot as snapshot_evolution

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


def build(refresh_notes=False, research_records=None):
    if research_records:
        snapshot_evolution(research_records, SNAPSHOTS / 'evolution.json')
    if refresh_notes:
        SNAPSHOTS.mkdir(exist_ok=True)
        for source, target in [('README.md', 'project.md'), ('loop.md', 'loop.md'),
                               ('controllers/reactive.py', 'reactive.py')]:
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
    evolution = json.loads((SNAPSHOTS / 'evolution.json').read_text())
    digest = hashlib.sha256(''.join((SNAPSHOTS / name).read_text() for name in
                                    ['project.md', 'loop.md', 'components.json', 'reactive.py',
                                     'results.json', 'experiment-report.md', 'evolution.json']).encode()).hexdigest()
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
        **render_evolution(evolution),
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
    shutil.copyfile(SNAPSHOTS / 'evolution.json', output / 'evolution.json')
    (output / 'sources').mkdir()
    for record in evolution['records']:
        (output / 'sources' / f'{record["id"]}.py').write_text(record['source'])
    # The reviewed report's only other links point into repository documentation.
    report = (SNAPSHOTS / 'experiment-report.md').read_text()
    report = re.sub(r'\[([^\]]+)\]\((?!results\.json\))[^)]+\)', r'\1', report)
    (output / 'experiment-report.md').write_text(report)
    print(f'Built LoopBlox introduction with {len(catalog)} components in {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-notes', action='store_true',
                        help='Refresh project, concept, component and baseline snapshots from the parent repository')
    parser.add_argument('--research-records', type=Path,
                        help='Snapshot the reviewed first three rounds from an explicit research/public directory')
    args = parser.parse_args()
    build(args.refresh_notes, args.research_records)
