"""Serve a local, read-only live monitor of existing continuous research campaigns."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import parse_qs, urlsplit

from loopblox import ROOT
from loopblox.research.campaign import status as campaign_status
from loopblox.research.codex import native_usage
from loopblox.research.research_summary import research_summary
from loopblox.research.trace_view import trace_view
from loopblox.research.visualize import public_directory, read_campaign, render_candidate_cards
from loopblox.runtime.controller import model_usage


ASSETS = {
    '/assets/loopblox-logo.png': (ROOT / 'docs/assets/loopblox-banner.png', 'image/png'),
    **{f'/assets/fonts/{name}.woff2':
       (ROOT / f'loopblox/chat_assets/assets/fonts/{name}.woff2', 'font/woff2')
       for name in ('DepartureMono-Regular', 'JetBrainsMono-Regular', 'SourceSerif4-Variable')},
}


def read_json(path, *, optional=False):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        if optional:
            return {}
        raise


def modified(path):
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0


def public_path(public, relative):
    public = Path(public).resolve()
    path = (public / relative).resolve()
    if not path.is_relative_to(public) or 'private' in path.relative_to(public).parts:
        raise ValueError('Record points outside public evidence.')
    return path


def session_directory(protocol):
    if protocol.get('benchmark') == 'AppWorld' and protocol.get('continuous') is True:
        return 'evaluation'
    if protocol.get('kind') == 'continuous_telecom':
        return 'research'
    return None


def campaign_identity(protocol):
    appworld = session_directory(protocol) == 'evaluation'
    code = appworld and bool(protocol.get('code_image'))
    return dict(benchmark='AppWorld' if appworld else 'τ²-bench telecom',
                task_count=len(protocol['task_ids']),
                interface=('Native code shell' if code else 'Public APIs') if appworld else
                          ('No-user' if protocol.get('solo_mode') else 'Interactive'),
                action_unit='code blocks' if code else 'actions')


def is_closed(result):
    # Early AppWorld runs recorded terminal status without a closing timestamp.
    return result.get('closed_at') is not None or result['status'] in {
        'completed', 'failed', 'interrupted', 'stopped'}


def started_at(root, result):
    return result.get('started_at') or modified(root / 'started.json') or None


def process_alive(pid, command):
    """Check a recorded local PID and exact command, without signalling it."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        process = subprocess.run(['ps', '-p', str(pid), '-o', 'stat=', '-o', 'args='],
                                 capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode == 1 and not process.stdout.strip():
        return False
    if process.returncode:
        return None
    fields = process.stdout.strip().split(None, 1)
    return bool(len(fields) == 2 and not fields[0].startswith('Z') and fields[1].endswith(command))


def host_alive(root, protocol):
    command = (f' -m loopblox.benchmarks.run_appworld --output {root} --frozen'
               if session_directory(protocol) == 'evaluation' else
               f' -m loopblox.research.campaign {root}')
    return process_alive(read_json(root / 'started.json', optional=True).get('pid'), command)


def supervision_directory(root):
    return (root.parent if root.parent.name.endswith('-supervision') else
            root.with_name(root.name + '-supervision'))


def campaign_name(root):
    if root.parent.name.endswith('-supervision'):
        return f'{root.parent.name.removesuffix("-supervision")} / {root.name}'
    return root.name


def supervision(root):
    """Project the supervisor onto its current evidence, including preparation gaps."""
    control = supervision_directory(root)
    state = read_json(control / 'state.json', optional=True)
    if not state:
        return None
    original = control.with_name(control.name.removesuffix('-supervision'))

    def attempt_path(value):
        path = Path(value)
        if path.is_symlink():
            raise ValueError('Supervisor attempt must not be a symlink.')
        path = path.resolve()
        if path != original and not (path.parent == control and re.fullmatch(r'attempt-\d+', path.name)):
            raise ValueError('Supervisor attempt points outside its campaign.')
        return path

    current = attempt_path(state['attempt'])
    # Preparation can precede protocol/result creation. Show the last saved
    # attempt's evidence while identifying the next attempt separately.
    attempts = [current, *(attempt_path(item['directory']) for item in reversed(state['attempts']))]
    displayed = next((p for p in attempts if (p / 'protocol.json').is_file() and (p / 'result.json').is_file()), None)
    if displayed != root:
        return None
    alive = process_alive(state.get('supervisor_pid'),
        f' -m loopblox.benchmarks.run_appworld --output {original} --frozen --continuous')
    phase = {'repairing': 'Infrastructure repair / recovery wait', 'blocked': 'Human input required',
             'stopped': 'Supervisor stopped', 'completed': 'Supervision complete',
             'failed': 'Supervisor failed'}.get(state['status'], 'Supervised research')
    if state['status'] == 'running' and (current != displayed or not (current / 'started.json').is_file()):
        phase = 'Preparing recovery attempt'
    elif state['status'] == 'running' and is_closed(read_json(current / 'result.json')):
        phase = 'Closing attempt / preparing recovery'
    return dict(status=state['status'], host_alive=alive, current_attempt=current.name, phase=phase,
                repair_count=len(state['repairs']), closed_attempts=len(state['attempts']),
                required_action=state.get('required_action') or
                    (state.get('incident') or {}).get('detail'),
                updated_at=modified(control / 'state.json'))


def run_snapshot(public, evaluation_id, row):
    """Task/scoring results and analysis are distinct stages of one recorded lane."""
    directory = public_path(public, f'evaluations/{evaluation_id}/{row["directory"]}')
    result = read_json(directory / 'result.json', optional=True)
    # The enclosing row is collected only after mandatory Jev analysis finishes.
    facts = {**row, **result} if row['status'] == 'running' else row
    semantic = read_json(directory / 'jev.json', optional=True) if row['status'] == 'running' else row.get('jev', {})
    trace = read_json(directory / 'trace.json', optional=True) if row['status'] == 'running' else {}
    calls = trace.get('component_calls', [])
    current = next((call for call in reversed(calls) if call['status'] == 'started'), None)
    latest = current or (calls[-1] if calls else {})
    usage = model_usage(trace['model_calls']) if trace else facts.get('agent_usage', {})
    verdict = facts.get('verification_verdict')
    # v10 retains failed split parents as evidence; only leaves are measurements,
    # matching analysis.jev.feedback's projection for finished rows.
    segments = [s for s in semantic.get('segments', []) if s.get('status') != 'split']
    if row['status'] == 'not_started':
        phase = 'Queued'
    elif row['status'] != 'running':
        phase = 'Finished' if semantic.get('status') == 'completed' else 'Closed without complete analysis'
    elif semantic:
        phase = 'Jev analysis' if semantic['status'] == 'running' else 'Finalizing analysis'
    elif result:
        phase = 'Awaiting Jev analysis'
    elif trace and trace['status'] != 'running':
        phase = 'Official scoring / task cleanup'
    else:
        phase = 'Executing task' if trace else 'Starting task'
    return dict(candidate_id=row['candidate_id'], task_id=row['task_id'], directory=row['directory'],
        status=row['status'], phase=phase, verdict=verdict, jev_status=semantic.get('status', 'not_started'),
        jev_completed=sum(s.get('status') == 'completed' for s in segments) if semantic else None,
        jev_total=len(segments) if semantic else None,
        component=latest.get('component'), component_status=latest.get('status'),
        actions=trace.get('actions_executed', facts.get('actions')),
        agent_model_calls=usage.get('model_calls'), agent_input_tokens=usage.get('model_input_tokens'),
        updated_at=max((modified(directory / name) for name in ('trace.json', 'result.json', 'jev.json')), default=0) or None,
        stop_reason=facts.get('stop_reason') or semantic.get('error'))


def snapshot(root, task=None, *, view='dashboard', candidate=None, run=None):
    root = Path(root).resolve()
    now = time.time()
    protocol = read_json(root / 'protocol.json')
    session = session_directory(protocol)
    if session is None:
        raise ValueError('Only continuous AppWorld and telecom campaigns are supported.')
    public = root / session / 'public'
    result = read_json(root / 'result.json')
    # The generic visualizer owns candidate comparisons, source validation and
    # recorded execution paths for both the live page and standalone exports.
    loops = (read_campaign(public, task, include_execution=view == 'dashboard')
             if (public / 'progress.json').is_file() else
             dict(progress={}, checkpoints=[], candidates=[], task=None, tasks=[]))
    progress, checkpoints = loops['progress'], loops['checkpoints']
    candidates = [dict(id=c['id'], iteration=c['iteration']) for c in loops['candidates']]
    evaluations = sorted((public / 'evaluations').glob('*/result.json'))
    evaluation = None
    if evaluations:
        batch = read_json(public_path(public, evaluations[-1].relative_to(public)))
        rows = [run_snapshot(public, batch['evaluation_id'], row) for row in batch['runs']]
        evaluation = dict(id=batch['evaluation_id'], status=batch['status'], feedback_ready=bool(batch.get('feedback_ready')),
            planned=len(rows), finished=sum(r['status'] not in ('not_started', 'running') for r in rows),
            scored=sum(r['verdict'] in ('pass', 'fail') for r in rows),
            passed=sum(r['verdict'] == 'pass' for r in rows), failed=sum(r['verdict'] == 'fail' for r in rows),
            missing=sum(r['status'] not in ('not_started', 'running') and r['verdict'] not in ('pass', 'fail') for r in rows),
            active=sum(r['status'] == 'running' for r in rows), queued=sum(r['status'] == 'not_started' for r in rows),
            jev_completed=sum(r['jev_status'] == 'completed' for r in rows), runs=rows)
    closed = is_closed(result)
    alive = host_alive(root, protocol) if not closed else None
    private = root / session / 'private'
    native = read_json(private / 'research-trace.json', optional=True)
    native_calls = native.get('calls', [])
    last_call = native_calls[-1] if native_calls else {}
    native_activity = private / 'codex-calls' / str(last_call.get('call_id', '')) / 'events.jsonl'
    activity = max([modified(root / 'result.json'), modified(public / 'progress.json'),
                    modified(private / 'research-trace.json'), modified(private / 'research-usage.json'),
                    modified(native_activity), modified(public / 'notes.md')]
                   + [r['updated_at'] or 0 for r in (evaluation or {}).get('runs', [])])
    if closed:
        phase = result.get('research_status') or result['status']
    elif alive is False:
        phase = 'Host process not found'
    elif (root / 'stop-request.json').exists():
        phase = 'Stopping / waiting for cleanup'
    elif (protocol.get('prior_attempt') or protocol.get('recovery') or {}).get('not_before', 0) > now:
        phase = 'Waiting for recovery window'
    elif evaluation and evaluation['status'] == 'running':
        phase = 'Evaluating baseline' if not progress.get('incumbent') else 'Evaluating candidate'
    elif last_call.get('status') == 'started':
        phase = 'Researcher working'
    elif progress.get('status') == 'researching':
        phase = 'Research / checkpoint transition'
    else:
        phase = 'Preparing research' if result['status'] == 'researching' else result['status']
    warnings = []
    accounting = {}
    researcher_usage = {}
    try:
        # Project recorded accounting only; never start a session or expose ledgers.
        if session == 'evaluation':
            prior = protocol.get('prior_accounting', {})
            usage = result.get('cumulative_usage')
            if 'cumulative_usage' not in result:
                current = (result['usage'] if 'usage' in result else
                           model_usage(read_json(private / 'research-usage.json', optional=True).get('calls', [])))
                previous = prior.get('usage', {})
                usage = ({key: value + previous.get(key, 0)
                          if value is not None and previous.get(key, 0) is not None else None
                          for key, value in current.items()} if current is not None else None)
            accounting = dict(cumulative_usage=usage,
                cumulative_task_runs=prior.get('task_runs', 0) + progress.get('task_runs_this_attempt', 0),
                cumulative_charged_seconds=result.get('cumulative_charged_seconds'))
            researcher_usage = native_usage(native_calls)
        else:
            accounting = campaign_status(root)
            totals = [item['usage'] for item in accounting.get('native_researcher_usage', [])]
            for key in ('input_tokens', 'output_tokens'):
                values = [item.get(key) for item in totals]
                researcher_usage[key] = sum(values) if values and all(v is not None for v in values) else None
    except (OSError, ValueError, KeyError, TypeError):
        warnings.append('Cumulative accounting is temporarily unavailable; it will be retried on refresh.')
    if alive is False and not closed:
        warnings.append('The recorded local host process is absent. The experiment has not written a closing result.')
    start = started_at(root, result)
    end = result.get('closed_at') if closed else now
    supervisor = supervision(root) if session == 'evaluation' else None
    if supervisor:
        activity = max(activity, supervisor['updated_at'])
        if supervisor['host_alive'] is True and supervisor['phase'] != 'Supervised research':
            phase = supervisor['phase']
        if supervisor['status'] in ('running', 'repairing') and supervisor['host_alive'] is False:
            warnings.append('The recorded supervisor process is absent; recovery is not confirmed as running.')
    data = dict(as_of=now, campaign=dict(id=root.name, name=campaign_name(root), path=str(root), status=result['status'],
        **campaign_identity(protocol),
        session_status=progress.get('status'), phase=phase, started_at=start, closed=closed, closed_at=result.get('closed_at'),
        wall_seconds=result.get('elapsed_seconds', max(0, end - start) if start and end else None), host_alive=alive,
        model=protocol.get('model', {}).get('model'), evaluation_workers=protocol.get('evaluation_workers', 1),
        completed_iterations=progress.get('completed_iterations', 0), incumbent=progress.get('incumbent'),
        pending_candidates=progress.get('pending_candidates', []), task_runs_this_attempt=progress.get('task_runs_this_attempt', 0),
        last_activity_at=activity, error=result.get('error'),
        recovery_from=(protocol.get('prior_attempt') or {}).get('directory') or protocol.get('recovery', {}).get('previous')),
        evaluation=evaluation, candidates=candidates, checkpoints=checkpoints,
        visualization=(None if view != 'dashboard' else
                       dict(task=loops['task'], tasks=loops['tasks'], html=render_candidate_cards(loops))),
        usage=accounting.get('cumulative_usage'), cumulative_task_runs=accounting.get('cumulative_task_runs'),
        cumulative_charged_seconds=accounting.get('cumulative_charged_seconds'),
        native_usage={key: researcher_usage.get(key) for key in ('input_tokens', 'output_tokens')},
        native_usage_scope='current_attempt' if session == 'evaluation' else 'cumulative',
        supervision=supervisor, warnings=warnings)
    if view == 'research':
        data['research'] = research_summary(public, loops)
        data['warnings'].extend(data['research'].get('warnings', []))
    elif view == 'trace':
        data['trace'] = trace_view(public, candidate=candidate, task=task, run=run)
        data['warnings'].extend(data['trace'].get('warnings', []))
    return data


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, path, port=8767):
        path = Path(path).resolve()
        if not path.is_dir():
            raise ValueError('The campaign or campaigns directory does not exist.')
        if (path / 'protocol.json').is_file():
            self.single = path
        elif path.name in ('research', 'evaluation', 'public'):
            _, self.single = public_directory(path)
        else:
            self.single = None
        self.path = path
        self.page = Path(__file__).with_name('dashboard.html').read_bytes()
        self.closed_snapshots = {}
        super().__init__(('127.0.0.1', port), Handler)

    def snapshot(self, root, task=None, *, view='dashboard', candidate=None, run=None):
        key = (root, task, view, candidate, run)
        supervised = (supervision_directory(root) / 'state.json').is_file()
        if key not in self.closed_snapshots or supervised:
            data = snapshot(root, task, view=view, candidate=candidate, run=run)
            data['campaign']['id'] = self.campaign_id(root)
            # Closed campaign records are immutable. Avoid repeatedly reading large
            # recovery ledgers; never cache an incomplete accounting projection.
            if data['campaign']['closed'] and not data['warnings'] and not supervised:
                self.closed_snapshots[key] = data
            return data
        return {**self.closed_snapshots[key], 'as_of': time.time()}

    def campaign_id(self, root):
        return root.name if self.single else root.relative_to(self.path).as_posix()

    def campaigns(self):
        campaigns, warnings = [], []
        collections = [self.path, *(self.path / name for name in ('appworld', 'tau2'))]
        paths = ([self.single] if self.single else
                 [p for directory in collections if directory.is_dir() and not directory.is_symlink()
                  for p in directory.iterdir() if p.is_dir() and not p.is_symlink()])
        # The supervisor owns one explicit level of recovery directories. Do not
        # recurse into frozen implementations, repair workspaces or private data.
        paths += [p for control in paths if control.name.endswith('-supervision')
                  and (control / 'state.json').is_file()
                  for p in control.iterdir() if re.fullmatch(r'attempt-\d+', p.name)
                  and p.is_dir() and not p.is_symlink()]
        for root in paths:
            try:
                protocol = read_json(root / 'protocol.json', optional=True)
                if session_directory(protocol) is None:
                    continue
                result = read_json(root / 'result.json')
                supervisor = supervision(root) if session_directory(protocol) == 'evaluation' else None
                live_supervisor = bool(supervisor and supervisor['host_alive'] is True
                                       and supervisor['status'] in ('running', 'repairing'))
                campaigns.append(dict(id=self.campaign_id(root), name=campaign_name(root), status=result['status'],
                    **campaign_identity(protocol),
                    started_at=started_at(root, result), closed=is_closed(result), closed_at=result.get('closed_at'),
                    is_live=live_supervisor or (not is_closed(result) and host_alive(root, protocol) is True),
                    created_at=modified(root / 'protocol.json')))
            except (OSError, ValueError, KeyError):
                warnings.append(f'Cannot read campaign {root.name}; it will be retried on refresh.')
        campaigns.sort(key=lambda c: c['started_at'] or c['created_at'], reverse=True)
        default = next((c for c in campaigns if c['is_live']), campaigns[0] if campaigns else None)
        return dict(campaigns=campaigns, default_campaign=default['id'] if default else None, warnings=warnings)

    def campaign(self, identifier):
        # Resolve only IDs discovered in the configured campaign collections.
        known = self.campaigns()['campaigns']
        if not any(c['id'] == identifier for c in known):
            raise ValueError('Unknown campaign.')
        return self.single or self.path / identifier


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, code, body, content_type):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; "
                         "style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                         "font-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        origin = self.headers.get('Origin')
        if self.headers.get('Host') not in hosts or (origin and origin not in {f'http://{h}' for h in hosts}):
            self.respond(403, b'Local dashboard requests only.', 'text/plain; charset=utf-8')
            return
        url = urlsplit(self.path)
        try:
            if url.path in ('/', '/research', '/trace'):
                self.respond(200, self.server.page, 'text/html; charset=utf-8')
                return
            if url.path in ASSETS:
                path, content_type = ASSETS[url.path]
                self.respond(200, path.read_bytes(), content_type)
                return
            if url.path == '/api/campaigns':
                data = self.server.campaigns()
            elif url.path == '/api/snapshot':
                query = parse_qs(url.query)
                identifier = query.get('campaign', [None])[0]
                root = self.server.campaign(identifier)
                view = query.get('view', ['dashboard'])[0]
                if view not in ('dashboard', 'research', 'trace'):
                    raise ValueError('Unknown dashboard view.')
                data = self.server.snapshot(root, query.get('task', [None])[0], view=view,
                                            candidate=query.get('candidate', [None])[0],
                                            run=query.get('run', [None])[0])
            else:
                self.respond(404, b'Not found.', 'text/plain; charset=utf-8')
                return
            self.respond(200, json.dumps(data, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
        except (OSError, ValueError, KeyError, TypeError):
            self.respond(503, json.dumps({'error': 'The requested records are unavailable or incomplete. Retrying is safe.'}).encode(),
                         'application/json; charset=utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path, nargs='?', default=ROOT / '.artifacts',
                        help='Campaign or directory containing AppWorld/telecom campaigns (default: .artifacts)')
    parser.add_argument('--port', type=int, default=8767, help='Local port (default: 8767)')
    args = parser.parse_args()
    try:
        server = DashboardServer(args.path, args.port)
    except (OSError, ValueError) as error:
        parser.exit(2, f'Cannot start dashboard: {error}\n')
    print(f'LoopBlox live dashboard: http://127.0.0.1:{server.server_port}/', flush=True)
    print(f'Reading {server.path}. Press Ctrl-C to close the dashboard; research continues independently.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
