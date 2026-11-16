import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('cli_contract', ROOT/'ops/github_inbox/cli_contract_v1.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def help_text(flags=None):
    return 'options:\n' + '\n'.join('  '+f+' VALUE  help' for f in (module.REQUIRED if flags is None else flags))


def test_realistic_declarations_and_private_prose_not_returned():
    result = module.audit_help(help_text()+'\nPRIVATE_SENTINEL')
    assert result['advertised_options_complete']
    assert not result['runtime_authorized'] and not result['installed_identity_verified']
    assert 'PRIVATE_SENTINEL' not in str(result)


@pytest.mark.parametrize('replacement', ['--input', '--in-place', '--in_extra'])
def test_prefix_collisions_do_not_prove_in(replacement):
    text = help_text([replacement if f == '--in' else f for f in module.REQUIRED])
    assert '--in' in text  # This passed the frozen substring check.
    assert module.audit_help(text)['missing_options'] == ['--in']


def test_usage_examples_and_description_do_not_advertise_provider():
    text = help_text(module.REQUIRED[:-1])+'\nUsage: hermes --provider NAME\nExamples: --provider NAME\n  --other VALUE  accepts --provider in documentation'
    assert module.audit_help(text)['missing_options'] == ['--provider']


def test_alias_and_equals_declarations():
    text = help_text().replace('  --query-file VALUE', '  -q, --query-file=FILE')
    assert module.audit_help(text)['advertised_options_complete']


@pytest.mark.parametrize('text', ['', '\x1b[31m  --in', 'x'*65537, None])
def test_unbounded_or_control_help_refuses(text):
    with pytest.raises(ValueError): module.audit_help(text)
