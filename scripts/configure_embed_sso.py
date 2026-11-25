"""Configure a registered confidential client for delegated embedded login."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re


def env_value(source, name):
    match = re.search(r'^' + re.escape(name) + r'=(.*)$', source, re.MULTILINE)
    return match.group(1).strip().strip('"\'') if match else ''


def set_env(source, name, value):
    line = name + '=' + value
    pattern = r'^' + re.escape(name) + r'=.*$'
    if re.search(pattern, source, re.MULTILINE):
        return re.sub(pattern, lambda _: line, source, flags=re.MULTILINE)
    return source.rstrip() + '\n' + line + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fancyqube-root', type=Path, required=True)
    parser.add_argument('--iam-root', type=Path, required=True)
    parser.add_argument('--client-id', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', args.client_id):
        parser.error('Invalid client id')
    fancy = args.fancyqube_root.resolve()
    iam = args.iam_root.resolve()
    if not (fancy / 'Project/settings.py').is_file() or not (iam / 'app/api/embed_sso.py').is_file():
        parser.error('Expected the fancyqube and iam-service project directories')
    local_path = fancy / '.aihub-embed-sso.json'
    env_path = iam / '.env'
    local = json.loads(local_path.read_text(encoding='utf-8')) if local_path.exists() else {}
    env = env_path.read_text(encoding='utf-8') if env_path.exists() else ''
    # A client secret is registered and hashed by IAM, never invented here.
    secret = os.environ.get('AIHUB_EMBED_CLIENT_SECRET', '')
    if not secret and local.get('client_id') == args.client_id:
        secret = local.get('client_secret', '')
    if not secret:
        secret = getpass.getpass('Registered IAM client_secret (hidden): ')
    if not isinstance(secret, str) or not 1 <= len(secret) <= 255 or any(c in secret for c in '\r\n\0'):
        parser.error('Invalid client secret; no files were changed')
    allowed = [value.strip() for value in env_value(env, 'EMBED_SSO_ALLOWED_CLIENT_IDS').split(',') if value.strip()]
    if args.client_id not in allowed:
        allowed.append(args.client_id)
    env = set_env(env, 'EMBED_SSO_ALLOWED_CLIENT_IDS', ','.join(allowed))
    local = {'client_id': args.client_id, 'client_secret': secret}
    local_path.write_text(json.dumps(local, indent=2) + '\n', encoding='utf-8')
    env_path.write_text(env, encoding='utf-8')
    print('Local user-token settings saved. Register this confidential secure_rs256 client in IAM first.')
    print('This command does not create or validate client registrations and does not restart services.')


if __name__ == '__main__':
    main()
