from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / 'skills' / 'analyze-project-claims'
SCRIPTS = SKILL_ROOT / 'scripts'
MAPPER = SCRIPTS / 'reconcile_component_map.py'
ENGINE_ROOT = SCRIPTS / '_internal' / 'component_evidence'

sys.path.insert(0, str(SCRIPTS))


class ComponentEvidenceEngineTests(unittest.TestCase):
    def load_identity(self):
        from _internal.component_evidence import identity

        return identity

    def test_checked_in_descriptor_matches_engine_bytes(self) -> None:
        identity = self.load_identity()
        descriptor = identity.verify_engine_descriptor(SKILL_ROOT)
        rebuilt = identity.build_engine_descriptor(SKILL_ROOT)

        self.assertEqual(descriptor, rebuilt)
        self.assertEqual(descriptor['provider_kind'], 'embedded')
        self.assertEqual(descriptor['engine_name'], 'component-evidence')
        self.assertRegex(descriptor['engine_digest'], r'^[0-9a-f]{64}$')
        self.assertNotIn(
            'references/component-evidence-engine.json',
            [entry['path'] for entry in descriptor['files']],
        )

    def test_engine_tamper_invalidates_descriptor(self) -> None:
        identity = self.load_identity()
        with tempfile.TemporaryDirectory(prefix='engine-identity-') as temporary:
            copied = Path(temporary) / 'skill'
            shutil.copytree(SKILL_ROOT, copied)
            mapper = copied / 'scripts' / 'reconcile_component_map.py'
            mapper.write_text(mapper.read_text(encoding='utf-8') + '\n# tampered\n', encoding='utf-8')

            with self.assertRaisesRegex(identity.EngineIdentityError, 'digest mismatch'):
                identity.verify_engine_descriptor(copied)

    def test_semantic_only_change_does_not_change_engine_digest(self) -> None:
        identity = self.load_identity()
        with tempfile.TemporaryDirectory(prefix='engine-boundary-') as temporary:
            copied = Path(temporary) / 'skill'
            shutil.copytree(SKILL_ROOT, copied)
            before = identity.verify_engine_descriptor(copied)['engine_digest']
            skill = copied / 'SKILL.md'
            skill.write_text(skill.read_text(encoding='utf-8') + '\nSemantic note.\n', encoding='utf-8')
            after = identity.verify_engine_descriptor(copied)['engine_digest']

            self.assertEqual(before, after)

    def test_internal_engine_has_no_semantic_network_or_delivery_imports(self) -> None:
        forbidden = {
            'http',
            'requests',
            'urllib',
            'problem_report',
            'update_policy',
            'record_scan',
            'subprocess',
        }
        observed: set[str] = set()
        for path in ENGINE_ROOT.glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    observed.update(alias.name.split('.')[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    observed.add(node.module.split('.')[0])

        self.assertTrue(observed.isdisjoint(forbidden), observed & forbidden)

    def test_verify_self_cli_reports_bound_embedded_identity(self) -> None:
        result = subprocess.run(
            [sys.executable, str(MAPPER), 'verify-self'],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['status'], 'verified')
        self.assertEqual(output['provider_kind'], 'embedded')
        self.assertRegex(output['engine_digest'], r'^[0-9a-f]{64}$')

    def test_build_self_cli_repairs_descriptor_in_copy(self) -> None:
        with tempfile.TemporaryDirectory(prefix='engine-build-') as temporary:
            copied = Path(temporary) / 'skill'
            shutil.copytree(SKILL_ROOT, copied)
            descriptor = copied / 'references' / 'component-evidence-engine.json'
            descriptor.write_text('{}\n', encoding='utf-8')
            result = subprocess.run(
                [sys.executable, str(copied / 'scripts' / 'reconcile_component_map.py'), 'build-self', '--write'],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            verified = subprocess.run(
                [sys.executable, str(copied / 'scripts' / 'reconcile_component_map.py'), 'verify-self'],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)


if __name__ == '__main__':
    unittest.main()
