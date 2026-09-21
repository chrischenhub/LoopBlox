"""Depth-first candidate ordering for an explicitly requested ResearchSession study."""

import ast
import copy
from dataclasses import replace

from loopblox.research.session import ResearchSession
from loopblox.runtime.components import catalog, validate
from loopblox.runtime.io import atomic_json


def check_component_calls(source, exposed):
    """Check provable literal API mistakes, without restricting dynamic Python."""
    contracts = catalog(exposed)
    for node in ast.walk(ast.parse(source)):
        if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
                or not isinstance(node.func.value, ast.Name) or node.func.value.id != 'env'
                or node.func.attr != 'component' or len(node.args) != 1
                or not isinstance(node.args[0], ast.Constant)
                or not isinstance(node.args[0].value, str)
                or any(keyword.arg is None for keyword in node.keywords)):
            continue
        name = node.args[0].value
        if name not in contracts:
            raise ValueError(f'Line {node.lineno}: component {name!r} is not exposed')
        schema = contracts[name]['parameters']
        supplied = {keyword.arg for keyword in node.keywords}
        missing = set(schema['required']) - supplied
        extra = supplied - set(schema['properties'])
        if missing or extra:
            raise ValueError(f'Line {node.lineno}, {name}: missing {sorted(missing)}, unknown {sorted(extra)}')
        for keyword in node.keywords:
            try:
                value = ast.literal_eval(keyword.value)
            except (ValueError, TypeError):
                continue
            validate(value, schema['properties'][keyword.arg])


def frontier(nodes, policy):
    """Derive the next parent in depth-first order; scores never prune descendants."""
    def visit(node, depth):
        if depth >= policy['depth']:
            return None
        children = [item for item in nodes if item['parent_id'] == node['candidate_id']]
        for child in children:
            result = visit(child, depth + 1)
            if result is not None:
                return result
        if len(children) < policy['width']:
            return node['candidate_id']
        return None
    return visit(nodes[0], 0)


class DFSResearchSession(ResearchSession):
    def __init__(self, *, dfs_policy, **arguments):
        super().__init__(**arguments)
        self.dfs_policy = dfs_policy
        self.state['dfs_nodes'] = [dict(candidate_id=self.starting_candidate, parent_id=None)]
        self.save()

    def dfs_view(self):
        nodes = self.state['dfs_nodes']
        completed = {}
        for node in nodes[1:]:
            for evaluation in self.state['evaluations']:
                if (evaluation['candidate_ids'] == [node['parent_id'], node['candidate_id']]
                        and len(evaluation['sampled_tasks']) == self.dfs_policy['batch']
                        and all(row.get('verification_verdict') in {'pass', 'fail'} for row in evaluation['runs'])):
                    completed[node['candidate_id']] = evaluation['evaluation_id']
        pending = next((node for node in nodes[1:] if node['candidate_id'] not in completed), None)
        room = self.max_task_runs - self.state['task_runs_used'] >= 4 * self.dfs_policy['batch']
        parent = (frontier(nodes, self.dfs_policy)
                  if room and len(nodes) - 1 < self.dfs_policy['nodes'] else None)
        return dict(policy=self.dfs_policy, nodes=[{**node, 'evaluation_id': completed.get(node['candidate_id'])}
                                                 for node in nodes],
                    pending=pending, next_parent_id=None if pending else parent,
                    completed_edges=len(completed),
                    instructions='Modify next_parent_id, save with parent_id, then evaluate [parent, child] on '
                                 'the full batch. Scores do not prune descendants. Read parent source and relevant '
                                 'traces. Selection is independent of the exploration frontier. Before finish, '
                                 'compare your proposed submission against the baseline in a new full-batch evaluation '
                                 'under the same frozen task policy.')

    def save(self):
        super().save()
        if hasattr(self, 'dfs_policy'):
            atomic_json(self.public / 'dfs.json', self.dfs_view())

    def save_candidate(self, arguments, timeout):
        if not hasattr(self, 'dfs_policy'):
            return super().save_candidate(arguments, timeout)
        view = self.dfs_view()
        parent = arguments.get('parent_id')
        if view['pending'] or parent is None or parent != view['next_parent_id']:
            self.reject('Read dfs.json: save one child of next_parent_id only after the pending comparison completes.')
        source = arguments.get('source')
        if isinstance(source, str):
            try:
                check_component_calls(source, self.experiment['exposed'])
            except (SyntaxError, ValueError, TypeError) as error:
                self.reject('Candidate API preflight: ' + str(error))
        receipt = super().save_candidate({key: value for key, value in arguments.items() if key != 'parent_id'}, timeout)
        if receipt['created']:
            self.state['dfs_nodes'].append(dict(candidate_id=receipt['candidate_id'], parent_id=parent))
            self.save()
        return {**receipt, 'dfs': self.dfs_view()}

    def evaluate(self, arguments, timeout):
        if not hasattr(self, 'dfs_policy') or not self.state['evaluations']:
            return super().evaluate(arguments, timeout)
        view = self.dfs_view()
        pending = view['pending']
        ids = arguments.get('candidate_ids')
        if arguments.get('n') != self.dfs_policy['batch'] or arguments.get('repeats', 1) != 1:
            self.reject(f"This DFS study uses complete n={self.dfs_policy['batch']}, repeats=1 batches.")
        if pending:
            if ids != [pending['parent_id'], pending['candidate_id']]:
                self.reject('Evaluate the pending parent and child together, parent first; see dfs.json.')
        elif (not isinstance(ids, list) or len(ids) not in (1, 2) or ids[0] != self.initial_candidates[0]
              or (len(ids) == 2 and ids[1] not in [node['candidate_id'] for node in view['nodes']])):
            self.reject('Without a pending child, use [baseline, proposed_submission] for a final full-batch check.')
        receipt = super().evaluate(arguments, timeout)
        return {**receipt, 'dfs': self.dfs_view()}

    def finish(self, arguments, timeout):
        candidate = arguments.get('candidate_id')
        checked = any(evaluation['candidate_ids'][0] == self.initial_candidates[0]
                      and candidate in evaluation['candidate_ids']
                      and len(evaluation['sampled_tasks']) == self.dfs_policy['batch']
                      and all(row.get('verification_verdict') in {'pass', 'fail'} for row in evaluation['runs'])
                      for evaluation in self.state['evaluations'])
        if self.dfs_view()['pending'] or not checked:
            self.reject('Finish requires no pending child and a complete full-batch baseline comparison of your submission.')
        return super().finish(arguments, timeout)

    def tools(self):
        tools = list(super().tools())
        for index, tool in enumerate(tools):
            if tool.capability_id == 'save_candidate':
                schema = copy.deepcopy(tool.parameters)
                schema['properties']['parent_id'] = dict(type='string', description='Current next_parent_id in dfs.json.')
                schema['required'].append('parent_id')
                tools[index] = replace(tool, parameters=schema, description=tool.description +
                    ' This DFS episode also requires parent_id from dfs.json. Modify that source; '
                    'each saved child must complete its paired evaluation before another child is saved.')
        return tuple(tools)
