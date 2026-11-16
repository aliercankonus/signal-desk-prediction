"""Dormant text-only CLI option declaration audit; never launches Hermes.

An advertised option is not proof of argument semantics, installed identity,
provider entitlement, isolation or task authority. No runtime caller is wired.
"""
import hashlib
import re

REQUIRED = ('--query-file', '--oneshot', '--quiet', '--in', '--max-turns',
            '--run-budget', '--provider')
_OPTION = re.compile(r'--[a-zA-Z][a-zA-Z0-9-]*(?![a-zA-Z0-9_-])')
_DECLARATION = re.compile(r'^\s+(?:-[A-Za-z0-9?],?\s+)?--[A-Za-z]')


def audit_help(help_text):
    """Accept bounded plain argparse/click-style option declaration lines only.

    Prose, usage, examples, option prefixes and diagnostic text cannot satisfy
    required options. Unknown formats fail closed. Raw help is never returned.
    """
    if not isinstance(help_text, str):
        raise ValueError('HELP_TYPE')
    raw = help_text.encode('utf-8')
    if not raw or len(raw) > 65536 or any(ord(c) < 32 and c not in '\n\r\t' for c in help_text):
        raise ValueError('HELP_FORMAT')
    declared = set()
    for line in help_text.splitlines():
        if not _DECLARATION.match(line):
            continue
        # Two or more spaces separate the option signature from its prose.
        signature = re.split(r'\s{2,}', line.strip(), maxsplit=1)[0]
        declared.update(_OPTION.findall(signature))
    missing = [flag for flag in REQUIRED if flag not in declared]
    return {'schema': 1, 'help_sha256': hashlib.sha256(raw).hexdigest(),
            'advertised_options_complete': not missing, 'missing_options': missing,
            'runtime_authorized': False, 'installed_identity_verified': False}
