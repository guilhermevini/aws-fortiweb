#!/usr/bin/env python3
"""Sync FortiWeb Cloud IP ranges into AWS WAFv2 IP sets.

Examples:
    aws-fortiweb                      # IPv4 and IPv6, downloaded from FortiWeb
    aws-fortiweb --version 4 --dry-run
    aws-fortiweb --source file        # use allowed_ips4.txt / allowed_ips6.txt
    aws-fortiweb --scope CLOUDFRONT   # global IP sets (us-east-1)

This module has no dependencies besides boto3, so it can also be copied to a
server and run directly with `python3 aws_fortiweb.py`.
"""

import argparse
import ipaddress
import os
import sys
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoRegionError

__version__ = '1.0.0'

FORTIWEB_URLS = {
    4: 'https://www.fortiweb-cloud.com/ips-v4',
    6: 'https://www.fortiweb-cloud.com/ips-v6',
}
LOCAL_FILES = {
    4: 'allowed_ips4.txt',
    6: 'allowed_ips6.txt',
}
# AWS WAFv2 limit of addresses per IP set
WAF_MAX_ADDRESSES = 10000
MAX_LOCK_RETRIES = 3


def default_local_file(version):
    """Look for the list in the current directory first, then next to this module (repository checkout)."""
    name = LOCAL_FILES[version]
    cwd_file = Path.cwd() / name
    return cwd_file if cwd_file.exists() else Path(__file__).with_name(name)


def download_list(version):
    url = FORTIWEB_URLS[version]
    req = urllib.request.Request(url, headers={'User-Agent': f'aws-fortiweb/{__version__}'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode('utf-8')


def normalize_ips(text, version):
    """Validate, deduplicate and sort the CIDRs. Raises ValueError on any invalid entry."""
    networks = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        try:
            network = ipaddress.ip_network(line, strict=False)
        except ValueError as e:
            raise ValueError(f'line {lineno}: {e}') from None
        if network.version != version:
            raise ValueError(f'line {lineno}: {line} is not IPv{version}')
        networks.add(network)

    if not networks:
        raise ValueError('IP list is empty')
    if len(networks) > WAF_MAX_ADDRESSES:
        raise ValueError(f'{len(networks)} addresses exceed the WAF limit of {WAF_MAX_ADDRESSES}')
    return [str(n) for n in sorted(networks)]


def find_ip_set(client, name, scope):
    """Return the summary of the IP set with the given name, walking through all pages."""
    kwargs = {'Scope': scope, 'Limit': 100}
    while True:
        response = client.list_ip_sets(**kwargs)
        for ip_set in response.get('IPSets', []):
            if ip_set['Name'] == name:
                return ip_set
        marker = response.get('NextMarker')
        if not marker or not response.get('IPSets'):
            return None
        kwargs['NextMarker'] = marker


def sync_ip_set(client, name, scope, version, ips, dry_run):
    summary = find_ip_set(client, name, scope)

    if summary is None:
        print(f"[IPv{version}] IP set '{name}' not found; it will be created with {len(ips)} addresses.")
        if not dry_run:
            client.create_ip_set(
                Name=name,
                Scope=scope,
                IPAddressVersion=f'IPV{version}',
                Addresses=ips,
                Description='FortiWeb Cloud addresses - managed by aws-fortiweb',
            )
            print(f"[IPv{version}] IP set '{name}' created.")
        return

    for attempt in range(1, MAX_LOCK_RETRIES + 1):
        current = client.get_ip_set(Name=name, Scope=scope, Id=summary['Id'])
        ip_set = current['IPSet']
        # AWS returns IPv6 addresses in exploded form (e.g. 2406:da17:0467::), so normalize before comparing
        existing = {str(ipaddress.ip_network(a, strict=False)) for a in ip_set['Addresses']}
        added = sorted(set(ips) - existing)
        removed = sorted(existing - set(ips))

        if not added and not removed:
            print(f"[IPv{version}] IP set '{name}' is already up to date ({len(ips)} addresses).")
            return

        print(f"[IPv{version}] IP set '{name}': +{len(added)} / -{len(removed)}")
        for ip in added:
            print(f'  + {ip}')
        for ip in removed:
            print(f'  - {ip}')

        if dry_run:
            return

        try:
            # update_ip_set replaces the whole set; the description must be sent again or it is cleared
            params = dict(Name=name, Scope=scope, Id=summary['Id'], Addresses=ips, LockToken=current['LockToken'])
            if ip_set.get('Description'):
                params['Description'] = ip_set['Description']
            client.update_ip_set(**params)
            print(f"[IPv{version}] IP set '{name}' updated.")
            return
        except client.exceptions.WAFOptimisticLockException:
            if attempt == MAX_LOCK_RETRIES:
                raise
            print(f'[IPv{version}] IP set was modified by another process; retrying...')


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='aws-fortiweb',
        description=f'Sync FortiWeb Cloud IP ranges into AWS WAFv2 IP sets (aws-fortiweb {__version__}).',
    )
    parser.add_argument('--version', choices=['4', '6', 'all'], default='all', help='IP version (default: all)')
    parser.add_argument(
        '--source',
        choices=['url', 'file'],
        default='url',
        help='download from FortiWeb (url) or use local files (file). Default: url',
    )
    parser.add_argument('--ipv4-file', type=Path, help='IPv4 list for --source file (default: allowed_ips4.txt)')
    parser.add_argument('--ipv6-file', type=Path, help='IPv6 list for --source file (default: allowed_ips6.txt)')
    parser.add_argument('--scope', choices=['REGIONAL', 'CLOUDFRONT'], default='REGIONAL')
    parser.add_argument('--region', help='AWS region (ignored with --scope CLOUDFRONT, which requires us-east-1)')
    parser.add_argument('--name-ipv4', default='FortiWeb-IPv4', help='IPv4 IP set name')
    parser.add_argument('--name-ipv6', default='FortiWeb-IPv6', help='IPv6 IP set name')
    parser.add_argument('--dry-run', action='store_true', help='show the changes without applying them')
    args = parser.parse_args(argv)

    versions = [4, 6] if args.version == 'all' else [int(args.version)]
    names = {4: args.name_ipv4, 6: args.name_ipv6}
    files = {4: args.ipv4_file or default_local_file(4), 6: args.ipv6_file or default_local_file(6)}
    # boto3 only reads AWS_DEFAULT_REGION, while the AWS CLI also honors AWS_REGION
    region = 'us-east-1' if args.scope == 'CLOUDFRONT' else args.region or os.environ.get('AWS_REGION')
    try:
        client = boto3.client('wafv2', region_name=region)
    except NoRegionError:
        print(
            'Error: no AWS region configured. Use --region, set AWS_REGION, or configure one in your profile.',
            file=sys.stderr,
        )
        return 1

    failures = 0
    for version in versions:
        try:
            text = download_list(version) if args.source == 'url' else files[version].read_text()
            ips = normalize_ips(text, version)
            sync_ip_set(client, names[version], args.scope, version, ips, args.dry_run)
        except (ValueError, OSError, ClientError, BotoCoreError) as e:
            print(f'[IPv{version}] Error: {e}', file=sys.stderr)
            failures += 1

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
