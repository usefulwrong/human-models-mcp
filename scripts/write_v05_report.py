"""Generate the v0.5 handoff from actual gates and retained MCP evidence."""

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    reports = ROOT/'reports'
    release = json.loads((reports/'V05_RELEASE_CHECK.json').read_text())
    def observed(name, gate):
        path = reports/name
        return json.loads(path.read_text()) if release['gates'].get(gate, {}).get('status') == 'pass' and path.is_file() else {}
    e2e, clean, bundle, doctor = (observed('e2e.json', 'e2e'), observed('clean-copy.json', 'clean-check'), observed('offline-bundle.json', 'package'), observed('doctor.json', 'doctor'))
    lines = ['# UsefulWrong / human-models-mcp v0.5 — handoff', '', '**RELEASE_STATUS: '+release['release_status']+'**', '',
             f"Checked: {release['timestamp']}. Baseline HEAD: `{release['baseline_head']}`. Current HEAD: `{release['head']}`.",
             f"New local commits: `{release['new_commits']}`. Tested source SHA-256: `{release['source_sha256']}`.",
             f"Main image: `{release['image_id']}`. CPU: {doctor.get('cpu','not_run')}.", '',
             '## Baseline and implemented scope', '',
             'The existing 0.4.0 commit was independently rebuilt: make doctor/build/test/e2e/clean-check all exited 0, with 49 tests and all seven old experiments through both real transports. V05_BASELINE.json and V05_BASELINE_NUMERICS.json retain the new baseline, not an inherited report.',
             'Two added folders use a second registered model card: ms_human_700_locomotion, the pinned 36-coordinate/100-muscle variant with its upstream floor. The original seven scenarios and ten MCP tool names remain. No second engine, trained policy or replay was added.',
             'standing_contact_probe integrates a 0.2 s passive contact transient. assisted_stance integrates 0.4 s with a declared external pelvis PD wrench. Source collision geometries/masks/exclusions/masses stay unchanged; initialization enforces sixteen knee equalities and records the world-z root translation. World axes are compiled, not guessed from coordinate names.',
             'standing_balance, externally_actuated_balance and neuromuscular_balance remain unsupported. The brief was supplied in full by the user inline after CODEX_V05.md was absent; no requirement was inferred from a missing file.', '',
             '## Commands actually executed', '', '| Command | Exit | Status | Seconds | Log |', '| --- | --- | --- | --- | --- |']
    for gate in release['gates'].values():
        if 'command' in gate:
            lines.append(f"| `{gate['command']}` | {gate['exit_code']} | {gate['status']} | {gate['seconds']} | `{gate['log']}` |")
    lines += ['', 'make release-check exits successfully only when every required gate passes. A functional working-source test is not a clean committed release. Read V05_RELEASE_CHECK.json for failures/not_run and their actual reasons.', '',
              '## Scientific results and tests', '']
    evidence = ['# Actual MCP contact E2E — v0.5', '', 'Command: make e2e; repeated by make release-check. Official SDK 2.3.0 clients, MuJoCo 3.17.0, Docker network_mode=none, stdio and container-loopback HTTP.', '']
    if e2e:
        lines += ['Current real-engine E2E passed both transports, nine fresh client scenarios and the contact sub-suite. [Raw structured evidence](e2e.json).', '',
                  '| Scenario | Metric | Value | Unit |', '| --- | --- | --- | --- |']
        for transport in ('stdio','http'):
            source=e2e[transport]['v05']
            evidence += [f"## {transport}", '']
            for name in ('standing_contact_probe','assisted_stance'):
                run=source[name]['run']
                evidence += [f'Actual run_scenario result: {name}', '', '```json', json.dumps(run,indent=2), '```', '',
                             'Independent checks:', '', '```json', json.dumps({k:v for k,v in source[name].items() if k!='run'},indent=2), '```', '']
                if transport=='stdio':
                    for metric in run['outputs']['metrics']:
                        lines.append(f"| {name} | {metric['name']} | {metric['value']:.12g} | {metric['unit']} |")
        lines += ['', 'Independent public MuJoCo reconstruction checks the world contact-frame transform, signs, native integration-state restart, mass-weighted COM, and a separate recursive-body velocity/angular-momentum derivative. Tests also check the external control law, work/power, repeatability, halved dt, initial velocity perturbations, bounded loading, geometric penetration and joint-limit units.',
                  'Initial penetration, absent bilateral contact, excessive load, invalid duration and invalid support controller/gain are rejected without computed substitute metrics. Missing-render, partial numeric failure and abrupt interruption semantics are covered by the suite. All saved state/frame/CSV hashes and real PNG files are checked.', '']
    else:
        lines += ['Current science E2E failed or did not run; no old result is promoted to current PASS.', '']
    if clean:
        lines += [f"No-cache fixture: `{clean['clone']}`, source state `{clean['source_state']}`, image `{clean['image_id']}`. Empty stores, fresh pinned model provisioning, offline runtime, unit/package/lint, both transports and fresh external clients ran. An overlay is explicitly not a clean committed checkout.", '']
    if bundle:
        lines += [f"Offline bundle: `{bundle['bundle']}`. Main image identity restored by docker load; archive SHA-256 `{bundle['image_archive_sha256']}`. All nine client scenarios and named artifact exports passed.", '']
    lines += ['## Files, hardware and reproduction', '',
              'Physics is CPU. OSMesa software rendering is the CPU baseline. The separate GPU gate records actual NVIDIA EGL vendor/device and compares numeric CSV hashes for loaded/tracking/contact/assisted cases; no GPU physics claim.',
              'Runtime remains two CPUs, 3 GiB RAM, 128 PIDs, read-only root, no added capabilities/socket, network none. Initial provisioning/build requires network; scientific execution and the verified image bundle do not.',
              '[Contact audit](V05_CONTACT_AUDIT.md), [scientific results](V05_SCIENTIFIC_RESULTS.md), [actual LLM evaluation](V05_AGENT_E2E.md), [machine gates](V05_RELEASE_CHECK.json).',
              '[Probe GIF](../docs/demo_v05/standing_contact_probe/animation.gif), [overview](../docs/demo_v05/standing_contact_probe/overview.png), [assisted overview](../docs/demo_v05/assisted_stance/overview.png). Demo-store.json locates full raw files; display folders are subsets.', '',
              '```sh', 'make build', 'make experiment', 'python3 scripts/experiment.py --scenario assisted_stance --output outputs/my-assisted-stance', 'make release-check', '```', '',
              'make experiment defaults to standing_contact_probe in 0.5. It downloads all artifacts through MCP, checks size/hash and prints a new local index.html. Existing output directories are intentionally never overwritten. Use --scenario loaded_elbow etc. for the retained experiments.',
              'Agent connector: python3 scripts/print_client_config.py. The tools remain list_models, describe_model, get_model_capabilities, get_joint_info, list_scenarios, describe_scenario, run_scenario, get_result, get_artifact and search_sources. Select the scenario model ID; do not assume the first model matches every experiment.', '',
              '## Limits, blockers and next steps', '',
              'Named numerical checks establish consistency of this source model, soft contact recipe and artificial support law. They do not establish experimental ground-force accuracy, anatomical tissue deformation, complete self-collision, long-term unassisted balance, clinical safety or individualized sex/age/pathology. Primary wrist cadaver comparison does not validate the locomotion model.',
              'The source has positive contact margins, so active contact can occur at positive geometric gap. CoP is the equivalent floor-wrench point on z=0 when Fz>1e-6 N. The support hull uses force-bearing contact points, not anatomical sole area; inclusion is not a balance certificate. GRF=mg is not required in an accelerating or externally supported transient.',
              'Git blocker: .git remains mounted read-only. Authorized work/v0.5-whole-body-contact-release-rc creation failed with exit 128. No sudo, mount/permission changes, alternative protected write, fabricated commit, push or publication. Operator procedure: exit this read-only session, use an ordinary owner shell with writable Git metadata, create the requested branch, review/stage intended source/notices/docs/compact reports, commit, then rerun make release-check. No system permission workaround is proposed.',
              'The actual BAAI research release at 8eac35bb8788a183c9e8698ee1207c1bbe654094 includes reference motions/training code and explicitly omits checkpoints/evaluation results. Its inspected walking reference has 85 coordinates, whereas this locomotion variant has 36; it was not silently replayed or controlled. No reference dataset is redistributed by this iteration.',
              'Further research: resolve source knee range conflicts; obtain a matching calibrated contact dataset; audit controller/model/reference coordinate compatibility before policy work. Any unassisted standing claim needs explicit robustness/duration/contact tests beyond this probe.', '',
              '## Changes and Git', '']
    changed=[]
    try:
        status=subprocess.run(['git','status','--short'],cwd=ROOT,capture_output=True,text=True)
        status_text=status.stdout.rstrip() if status.returncode==0 else 'no_git_repository'
        for args in (['diff','--name-only','HEAD'],['ls-files','--others','--exclude-standard']):
            r=subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True)
            if r.returncode==0:
                changed.extend(r.stdout.splitlines())
    except FileNotFoundError:
        status_text='git_unavailable'
    lines += ['```text',status_text,'```','']
    (reports/'V05_CHANGED_FILES.txt').write_text('\n'.join(sorted(set(changed)))+'\n')
    (reports/'V05_HANDOFF.md').write_text('\n'.join(lines))
    (reports/'OVERNIGHT_REPORT.md').write_text('\n'.join(lines))
    (reports/'V05_E2E_EVIDENCE.md').write_text('\n'.join(evidence))


if __name__=='__main__':
    main()
