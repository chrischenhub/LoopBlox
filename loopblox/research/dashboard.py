"""Serve a local, read-only live monitor of existing continuous research campaigns."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import parse_qs, urlsplit

from loopblox import ROOT
from loopblox.research.campaign import status as campaign_status
from loopblox.research.research_summary import research_summary
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


def host_alive(root):
    """Check the recorded local PID and command, without signalling the experiment."""
    pid = read_json(root / 'started.json', optional=True).get('pid')
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
    return bool(len(fields) == 2 and not fields[0].startswith('Z')
                and fields[1].endswith(f' -m loopblox.research.campaign {root}'))


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
    segments = semantic.get('segments', [])
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


def snapshot(root, task=None, *, research=False):
    root = Path(root).resolve()
    now = time.time()
    public = root / 'research/public'
    protocol = read_json(root / 'protocol.json')
    if protocol.get('kind') != 'continuous_telecom':
        raise ValueError('Only continuous telecom campaigns are supported.')
    result = read_json(root / 'result.json')
    # The generic visualizer owns candidate comparisons, source validation and
    # recorded execution paths for both the live page and standalone exports.
    loops = (read_campaign(public, task) if (public / 'progress.json').is_file() else
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
    closed = result.get('closed_at') is not None
    alive = host_alive(root) if not closed else None
    private = root / 'research/private'
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
    elif protocol.get('recovery', {}).get('not_before', 0) > now:
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
    try:
        # This is the existing read-only accounting owner. Never call write_report,
        # instantiate a session, or expose the private ledgers/request bodies.
        accounting = campaign_status(root)
    except (OSError, ValueError, KeyError, TypeError):
        warnings.append('Cumulative accounting is temporarily unavailable; it will be retried on refresh.')
    if alive is False and not closed:
        warnings.append('The recorded local host process is absent. The experiment has not written a closing result.')
    native_totals = [item['usage'] for item in accounting.get('native_researcher_usage', [])]
    native_usage = {}
    for key in ('input_tokens', 'output_tokens'):
        values = [item.get(key) for item in native_totals]
        native_usage[key] = sum(values) if values and all(value is not None for value in values) else None
    start = result.get('started_at')
    data = dict(as_of=now, campaign=dict(id=root.name, name=root.name, path=str(root), status=result['status'],
        session_status=progress.get('status'), phase=phase, started_at=start, closed_at=result.get('closed_at'),
        wall_seconds=result.get('elapsed_seconds', max(0, now - start) if start else None), host_alive=alive,
        model=protocol.get('model', {}).get('model'), evaluation_workers=protocol.get('evaluation_workers', 1),
        completed_iterations=progress.get('completed_iterations', 0), incumbent=progress.get('incumbent'),
        pending_candidates=progress.get('pending_candidates', []), task_runs_this_attempt=progress.get('task_runs_this_attempt', 0),
        last_activity_at=activity, error=result.get('error'), recovery_from=protocol.get('recovery', {}).get('previous')),
        evaluation=evaluation, candidates=candidates, checkpoints=checkpoints,
        visualization=(None if research else
                       dict(task=loops['task'], tasks=loops['tasks'], html=render_candidate_cards(loops))),
        usage=accounting.get('cumulative_usage'), cumulative_task_runs=accounting.get('cumulative_task_runs'),
        cumulative_charged_seconds=accounting.get('cumulative_charged_seconds'), native_usage=native_usage, warnings=warnings)
    if research:
        data['research'] = research_summary(public, loops)
        data['warnings'].extend(data['research'].get('warnings', []))
    return data


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, path, port=8767):
        path = Path(path).resolve()
        if not path.is_dir():
            raise ValueError('The campaign or campaigns directory does not exist.')
        if (path / 'protocol.json').is_file():
            self.single = path
        elif path.name in ('research', 'public'):
            _, self.single = public_directory(path)
        else:
            self.single = None
        self.path = path
        self.page = Path(__file__).with_name('dashboard.html').read_bytes()
        self.closed_snapshots = {}
        super().__init__(('127.0.0.1', port), Handler)

    def snapshot(self, root, task=None, *, research=False):
        key = (root, task, research)
        if key not in self.closed_snapshots:
            data = snapshot(root, task, research=research)
            # Closed campaign records are immutable. Avoid repeatedly reading large
            # recovery ledgers; never cache an incomplete accounting projection.
            if data['campaign']['closed_at'] is not None and not data['warnings']:
                self.closed_snapshots[key] = data
            return data
        return {**self.closed_snapshots[key], 'as_of': time.time()}

    def campaigns(self):
        campaigns, warnings = [], []
        paths = [self.single] if self.single else [p for p in self.path.iterdir() if p.is_dir() and not p.is_symlink()]
        for root in paths:
            try:
                protocol = read_json(root / 'protocol.json', optional=True)
                if protocol.get('kind') != 'continuous_telecom':
                    continue
                result = read_json(root / 'result.json')
                campaigns.append(dict(id=root.name, name=root.name, status=result['status'],
                    started_at=result.get('started_at'), closed_at=result.get('closed_at'),
                    is_live=result.get('closed_at') is None and host_alive(root) is True,
                    created_at=modified(root / 'protocol.json')))
            except (OSError, ValueError, KeyError):
                warnings.append(f'Cannot read campaign {root.name}; it will be retried on refresh.')
        campaigns.sort(key=lambda c: c['started_at'] or c['created_at'], reverse=True)
        default = next((c for c in campaigns if c['is_live']), campaigns[0] if campaigns else None)
        return dict(campaigns=campaigns, default_campaign=default['id'] if default else None, warnings=warnings)

    def campaign(self, identifier):
        # IDs come only from the configured directory's direct campaign children.
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
            if url.path in ('/', '/research'):
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
                data = self.server.snapshot(root, query.get('task', [None])[0],
                                            research=query.get('view', [None])[0] == 'research')
            else:
                self.respond(404, b'Not found.', 'text/plain; charset=utf-8')
                return
            self.respond(200, json.dumps(data, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
        except (OSError, ValueError, KeyError, TypeError):
            self.respond(503, json.dumps({'error': 'The requested records are unavailable or incomplete. Retrying is safe.'}).encode(),
                         'application/json; charset=utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path, nargs='?', default=ROOT / '.artifacts/tau2',
                        help='Campaign or directory of campaigns (default: .artifacts/tau2)')
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
