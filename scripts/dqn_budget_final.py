"""One budget-final benchmark under the allocation registered before teacher32 outcomes.

The ordinary final runner retains its competitive-validation gate. This driver explicitly admits a
verified losing validation policy for the originally requested held-out measurement. It never relaxes
the final reliable-win criterion, baseline, sample counts, seeds or original absolute deadline.
Run from a new immutable snapshot only after our research worker exits. No source-run choice on CLI.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import dqn_final as final

PLAN_SHA256 = '3ae02e8740f2b9e4d2ec111655b37d3ca8ea3877e10060738a4256b831571f74'


def worker_alive(pid):
    """Read-only process liveness; never use Windows os.kill even with signal zero."""
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE; no mutation rights
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: no such process
            return False
        raise ctypes.WinError(error)
    try:
        status = kernel.WaitForSingleObject(handle, 0)
        if status not in (0, 258):  # WAIT_OBJECT_0, WAIT_TIMEOUT
            raise ctypes.WinError(ctypes.get_last_error())
        return status == 258
    finally:
        kernel.CloseHandle(handle)


def load_plan():
    path = ROOT / 'runs/double-dqn/budget-finalization-v1/plan.json'
    if final.sha(path) != PLAN_SHA256:
        raise ValueError('Budget allocation differs from the plan registered before teacher outcomes')
    plan = json.loads(path.read_text())
    if (plan['absolute_deadline_unix'] != final.DEADLINE or plan['baseline_commit'] != final.BASE
            or [(b['field'], b['seed']) for b in plan['final_blocks']] != list(final.BLOCKS)
            or any(b['pairings'] != 1000 for b in plan['final_blocks'])):
        raise ValueError('Original final blocks, baseline or deadline changed')
    return path, plan


def forecast(plan, recipe):
    budget = plan['runtime_forecast']
    if recipe['mode'] not in ('planning', 'direct', 'average'):
        raise ValueError('Unknown inference method')
    seconds = budget['planning_seconds_per_battle'] if recipe['mode'] == 'planning' else budget['direct_or_average_seconds_per_battle']
    return ((budget['final_battles'] + budget['canary_battles']) * seconds
            * budget['safety_multiplier'] + budget['closing_reserve_seconds'])


def choose(plan, records, decision_unix):
    """Rank fresh validation only, subject to the preregistered time forecast; first wins ties."""
    eligible = [record for record in records if record['status'] == 'complete'
                and record['forecast_seconds'] <= plan['absolute_deadline_unix'] - decision_unix]
    if not eligible:
        raise ValueError('No complete candidate fits the original remaining budget; do not extend it')
    return max(eligible, key=lambda record: record['score'])


def resolve_selection():
    path, plan = load_plan()
    # The teacher controller clears launch.json's worker_pid on successful completion.
    # The queue preserves the original PID/start identity through that normal transition.
    research = json.loads((path.parent / 'queue.json').read_text())['research_worker']
    if worker_alive(research['pid']):
        raise RuntimeError('Research worker is still live; refuse a duplicate numerical worker')
    directory = path.parent
    decision_path = directory / 'selection.json'
    previous = json.loads(decision_path.read_text()) if decision_path.exists() else None
    now = time.time()
    decision_unix = previous['decided_unix'] if previous else now
    if not plan['registered_unix'] <= decision_unix < plan['absolute_deadline_unix']:
        raise ValueError('Invalid selection instant or expired original deadline')
    teacher_result = ROOT / 'runs/double-dqn/teacher32-v1/result.json'
    if not teacher_result.exists() and decision_unix < plan['research_cutoff_unix']:
        raise RuntimeError('Teacher study incomplete before research cutoff; preserve its allocation')
    records = []
    for name in plan['candidate_order']:
        source = ROOT / 'runs/double-dqn' / name
        if not (source / 'result.json').exists():
            if name != 'teacher32-v1':
                raise ValueError('Previously completed candidate evidence is missing')
            records.append({'source_run': name, 'status': 'incomplete at research cutoff'})
            continue
        # All ordinary identity/source/selection/fresh-evidence checks stay active; only the
        # additional competitive-validation gate is waived for this explicitly labelled benchmark.
        model, _, recipe, confirmation = final.selection(name, False, require_competitive=False)
        plan_path = source / ('trial_plan.json' if name == 'relational-v1' else 'plan.json')
        records.append({'source_run': name, 'status': 'complete', 'model_sha256': final.sha(model),
            'model': model.name, 'recipe': recipe, 'score': confirmation['score'],
            'margin95': confirmation['margin95'], 'lower95': confirmation['lower95'],
            'upper95': confirmation['upper95'], 'confirmation_seed': confirmation['seed'],
            'result_sha256': final.sha(source / 'result.json'), 'plan_sha256': final.sha(plan_path),
            'forecast_seconds': forecast(plan, recipe)})
    selected = choose(plan, records, decision_unix)
    decision = {'plan_sha256': PLAN_SHA256, 'decided_unix': decision_unix,
        'selected_source': selected['source_run'], 'selected_model_sha256': selected['model_sha256'],
        'selected_recipe': selected['recipe'], 'candidates': records,
        'research_worker_pid': research['pid'], 'research_worker_started_utc': research['started_utc'],
        'research_worker_confirmed_exited': True,
        'selection_rule': plan['selection_rule'], 'validation_gate_amendment': plan['validation_gate_amendment']}
    # This lock is written before the canary. Canary outcomes cannot change the chosen policy.
    final.lock(decision_path, decision)
    receipt = {'plan_sha256': PLAN_SHA256, 'selection_sha256': final.sha(decision_path),
               'validation_gate_amendment': plan['validation_gate_amendment']}
    return selected['source_run'], receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canary', action='store_true')
    args = parser.parse_args()
    source, receipt = resolve_selection()
    print(json.dumps({'event': 'budget_final_selection_locked', 'source_run': source, **receipt}), flush=True)
    final.execute(source, args.canary, budget_receipt=receipt)


if __name__ == '__main__':
    main()
