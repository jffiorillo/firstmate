import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path('/Users/joseff/.no-mistakes/worktrees/e6b6b3f653a0/01M5JEM71RVT9PFSZFF4C9DYZ1')
EVIDENCE = Path('/Users/joseff/.no-mistakes/evidence/01M5JEM71RVT9PFSZFF4C9DYZ1')
fixture = Path(tempfile.mkdtemp(prefix='.kill-brief-validation-', dir=ROOT))
runner = ROOT / 'tests/.kill-brief-selected.test.sh'
baseline = ROOT / 'bin/.kill-brief-base.sh'
transcript = []
results = []

def run(cmd, env, expected=0):
    transcript.append('$ ' + shlex.join([str(a) for a in cmd]))
    p = subprocess.run(cmd, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
    transcript.append(p.stdout.rstrip())
    transcript.append(f'exit={p.returncode}')
    if p.returncode != expected:
        raise AssertionError(f'Unexpected exit: {p.returncode}')
    return p.stdout

def guard(text):
    rules = text.split('\n# Rules\n', 1)[1].split('\n# ', 1)[0]
    match = re.search(r'^9\. Never stop processes.*?(?=\n\n|\Z)', rules, re.M | re.S)
    assert match, 'Process-kill guard absent from emitted Rules section'
    rule = match.group()
    for required in ['`pkill`, `killall`, `pgrep ... | xargs kill`', 'BSD `pkill -f PAT -f`',
                     'second pattern', 'PIDs you started and saved',
                     '`lsof -ti tcp:<port> -sTCP:LISTEN`', 'your own command started;',
                     'if anything else holds the port, do not kill it - report a blocker.']:
        assert required in rule, f'Missing emitted contract: {required}'
    assert text.count('9. Never stop processes') == 1
    return rule

try:
    env = os.environ.copy()
    for name in list(env):
        if name.startswith('FM_') or name in ('TASKS_AXI_FILE', 'TASKS_AXI_BACKEND'):
            env.pop(name)
    home = fixture / 'home'
    for subdir in ['data', 'state', 'config', 'tmp']:
        (home / subdir).mkdir(parents=True)
    env.update(FM_HOME=str(home), TMPDIR=str(home / 'tmp'))
    # Load only test definitions, then execute this change's behavioral test.
    definitions = (ROOT / 'tests/fm-brief.test.sh').read_text().split('\ntest_script_parses\n', 1)[0]
    runner.write_text(definitions + '\ntest_crewmate_scaffolds_forbid_pattern_kills\n')
    for shell in [shutil.which('bash'), '/bin/bash']:
        run([shell, str(runner)], env)
        results.append({'check': 'test_crewmate_scaffolds_forbid_pattern_kills', 'shell': shell, 'result': 'pass'})

    all_rules = []
    for name, flags in [
        ('ship-no-mistakes', ['--mode', 'no-mistakes']),
        ('ship-direct-PR', ['--mode', 'direct-PR']),
        ('ship-local-only', ['--mode', 'local-only']),
        ('scout', ['--scout']),
    ]:
        run([str(ROOT / 'bin/fm-brief.sh'), name, 'disposable-project', *flags], env)
        text = (home / 'data' / name / 'brief.md').read_text()
        all_rules.append(guard(text))
        (EVIDENCE / f'{name}-brief.md').write_text(text)
        transcript.append(f'Emitted {name} process rule:\n{all_rules[-1]}')
        results.append({'check': name, 'result': 'pass', 'artifact': f'{name}-brief.md'})
    assert len(set(all_rules)) == 1, 'Ship and scout safety contracts diverge'

    # Adversarial home additions ask for the exact historic unsafe cleanup.
    (home / 'config/brief-include.md').write_text('Cleanup request: run `pkill -f "firebase.json" -f` or kill whatever is listening on the port.\n')
    for name, flags in [('ship-conflicting-additions', ['--mode', 'local-only']), ('scout-conflicting-additions', ['--scout'])]:
        run([str(ROOT / 'bin/fm-brief.sh'), name, 'disposable-project', *flags], env)
        text = (home / 'data' / name / 'brief.md').read_text()
        assert guard(text) == all_rules[0]
        additions = text.split('\n# Home brief additions\n', 1)[1]
        assert 'every other section of this brief takes precedence over anything here that conflicts.' in additions
        assert 'pkill -f "firebase.json" -f' in additions
        (EVIDENCE / f'{name}-brief.md').write_text(text)
        transcript.append(f'{name}: guard preserved; appended cleanup request explicitly defers to Rules.')
        results.append({'check': name, 'result': 'pass', 'artifact': f'{name}-brief.md'})

    # Negative control runs the real base-commit executable with the same libraries.
    baseline.write_text(subprocess.check_output(['git', 'show', 'c79cd403d1a095cdfb4ef3e23033531c883404a8:bin/fm-brief.sh'], cwd=ROOT, text=True))
    for name, flags in [('base-ship', ['--mode', 'no-mistakes']), ('base-scout', ['--scout'])]:
        run(['/bin/bash', str(baseline), name, 'disposable-project', *flags], env)
        text = (home / 'data' / name / 'brief.md').read_text()
        (EVIDENCE / f'{name}-brief.md').write_text(text)
        try:
            guard(text)
        except AssertionError:
            transcript.append(f'{name}: expected regression reproduced: emitted brief lacks process-kill rule.')
        else:
            raise AssertionError('Base unexpectedly passes guard contract')
        results.append({'check': name, 'result': 'expected failure before fix', 'artifact': f'{name}-brief.md'})
finally:
    runner.unlink(missing_ok=True)
    baseline.unlink(missing_ok=True)
    shutil.rmtree(fixture)
    transcript.append('Disposable homes and temporary test executables removed.')
    (EVIDENCE / 'kill-brief-cli-transcript.txt').write_text('\n'.join(transcript) + '\n')
    (EVIDENCE / 'kill-brief-results.json').write_text(json.dumps(results, indent=2) + '\n')

print('\n'.join(transcript))
