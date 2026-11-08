import sys

import boto3
import pytest
from botocore.stub import ANY, Stubber

import update_ip_sets as m

ARN = 'arn:aws:wafv2:us-east-1:123456789012:regional/ipset/x/x'


def summary(name, ip_set_id):
    return {'Name': name, 'Id': ip_set_id, 'LockToken': 't', 'ARN': ARN}


def ip_set(name, ip_set_id, version, addresses, description='d'):
    return {
        'Name': name,
        'Id': ip_set_id,
        'ARN': ARN,
        'IPAddressVersion': f'IPV{version}',
        'Addresses': addresses,
        'Description': description,
    }


@pytest.fixture
def waf():
    client = boto3.client('wafv2', region_name='us-east-1', aws_access_key_id='x', aws_secret_access_key='x')
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


# normalize_ips


def test_normalize_dedupes_sorts_and_ignores_comments():
    text = '10.0.0.5/8 # comment\n\n1.1.1.1/32\n1.1.1.1/32\n'
    assert m.normalize_ips(text, 4) == ['1.1.1.1/32', '10.0.0.0/8']


def test_normalize_compresses_ipv6():
    assert m.normalize_ips('2406:da17:0467:6301:0000:0000:0000:0001/128', 6) == ['2406:da17:467:6301::1/128']


@pytest.mark.parametrize(
    ('text', 'version', 'message'),
    [
        ('2600::/32', 4, 'is not IPv4'),
        ('1.1.1.1/32', 6, 'is not IPv6'),
        ('garbage', 4, 'line 1'),
        ('\n# only comments\n', 6, 'empty'),
    ],
)
def test_normalize_rejects_invalid_input(text, version, message):
    with pytest.raises(ValueError, match=message):
        m.normalize_ips(text, version)


def test_normalize_rejects_lists_over_waf_limit(monkeypatch):
    monkeypatch.setattr(m, 'WAF_MAX_ADDRESSES', 1)
    with pytest.raises(ValueError, match='exceed'):
        m.normalize_ips('1.1.1.1/32\n2.2.2.2/32', 4)


@pytest.mark.parametrize('version', [4, 6])
def test_bundled_lists_are_valid(version):
    assert m.normalize_ips(m.LOCAL_FILES[version].read_text(), version)


# find_ip_set


def test_find_ip_set_walks_pages(waf):
    client, stubber = waf
    stubber.add_response(
        'list_ip_sets', {'IPSets': [summary('Other', 'a' * 8)], 'NextMarker': 'p2'}, {'Scope': 'REGIONAL', 'Limit': 100}
    )
    stubber.add_response(
        'list_ip_sets',
        {'IPSets': [summary('FortiWeb-IPv4', 'b' * 8)]},
        {'Scope': 'REGIONAL', 'Limit': 100, 'NextMarker': 'p2'},
    )
    assert m.find_ip_set(client, 'FortiWeb-IPv4', 'REGIONAL')['Id'] == 'b' * 8


def test_find_ip_set_returns_none_when_missing(waf):
    client, stubber = waf
    stubber.add_response('list_ip_sets', {'IPSets': []}, {'Scope': 'REGIONAL', 'Limit': 100})
    assert m.find_ip_set(client, 'FortiWeb-IPv4', 'REGIONAL') is None


# sync_ip_set


def test_sync_creates_missing_ip_set(waf):
    client, stubber = waf
    stubber.add_response('list_ip_sets', {'IPSets': []}, {'Scope': 'REGIONAL', 'Limit': 100})
    stubber.add_response(
        'create_ip_set',
        {'Summary': summary('FortiWeb-IPv6', 'c' * 8)},
        {
            'Name': 'FortiWeb-IPv6',
            'Scope': 'REGIONAL',
            'IPAddressVersion': 'IPV6',
            'Addresses': ['2600::/32'],
            'Description': ANY,
        },
    )
    m.sync_ip_set(client, 'FortiWeb-IPv6', 'REGIONAL', 6, ['2600::/32'], dry_run=False)


def test_sync_dry_run_does_not_create(waf, capsys):
    client, stubber = waf
    stubber.add_response('list_ip_sets', {'IPSets': []}, {'Scope': 'REGIONAL', 'Limit': 100})
    m.sync_ip_set(client, 'FortiWeb-IPv4', 'REGIONAL', 4, ['1.1.1.1/32'], dry_run=True)
    assert 'will be created' in capsys.readouterr().out


def test_sync_updates_and_keeps_description(waf, capsys):
    client, stubber = waf
    stubber.add_response('list_ip_sets', {'IPSets': [summary('FortiWeb-IPv4', 'b' * 8)]})
    stubber.add_response(
        'get_ip_set', {'IPSet': ip_set('FortiWeb-IPv4', 'b' * 8, 4, ['1.1.1.1/32', '9.9.9.9/32']), 'LockToken': 'L1'}
    )
    stubber.add_response(
        'update_ip_set',
        {'NextLockToken': 'L2'},
        {
            'Name': 'FortiWeb-IPv4',
            'Scope': 'REGIONAL',
            'Id': 'b' * 8,
            'Addresses': ['1.1.1.1/32', '2.2.2.2/32'],
            'LockToken': 'L1',
            'Description': 'd',
        },
    )
    m.sync_ip_set(client, 'FortiWeb-IPv4', 'REGIONAL', 4, ['1.1.1.1/32', '2.2.2.2/32'], dry_run=False)
    out = capsys.readouterr().out
    assert '+ 2.2.2.2/32' in out
    assert '- 9.9.9.9/32' in out


def test_sync_ignores_exploded_ipv6_returned_by_aws(waf, capsys):
    """Regression: AWS returns IPv6 in exploded form, which must not be reported as a change."""
    client, stubber = waf
    stubber.add_response('list_ip_sets', {'IPSets': [summary('FortiWeb-IPv6', 'c' * 8)]})
    stubber.add_response(
        'get_ip_set',
        {
            'IPSet': ip_set('FortiWeb-IPv6', 'c' * 8, 6, ['2406:da17:0467:6301:0000:0000:0000:0001/128']),
            'LockToken': 'L1',
        },
    )
    m.sync_ip_set(client, 'FortiWeb-IPv6', 'REGIONAL', 6, ['2406:da17:467:6301::1/128'], dry_run=False)
    assert 'already up to date' in capsys.readouterr().out


def test_sync_retries_on_lock_conflict(waf):
    client, stubber = waf
    current = ip_set('FortiWeb-IPv4', 'b' * 8, 4, ['9.9.9.9/32'])
    stubber.add_response('list_ip_sets', {'IPSets': [summary('FortiWeb-IPv4', 'b' * 8)]})
    stubber.add_response('get_ip_set', {'IPSet': current, 'LockToken': 'L1'})
    stubber.add_client_error('update_ip_set', 'WAFOptimisticLockException')
    stubber.add_response('get_ip_set', {'IPSet': current, 'LockToken': 'L2'})
    stubber.add_response('update_ip_set', {'NextLockToken': 'L3'})
    m.sync_ip_set(client, 'FortiWeb-IPv4', 'REGIONAL', 4, ['1.1.1.1/32'], dry_run=False)


def test_sync_gives_up_after_max_lock_retries(waf):
    client, stubber = waf
    current = ip_set('FortiWeb-IPv4', 'b' * 8, 4, ['9.9.9.9/32'])
    stubber.add_response('list_ip_sets', {'IPSets': [summary('FortiWeb-IPv4', 'b' * 8)]})
    for _ in range(m.MAX_LOCK_RETRIES):
        stubber.add_response('get_ip_set', {'IPSet': current, 'LockToken': 'L'})
        stubber.add_client_error('update_ip_set', 'WAFOptimisticLockException')
    with pytest.raises(client.exceptions.WAFOptimisticLockException):
        m.sync_ip_set(client, 'FortiWeb-IPv4', 'REGIONAL', 4, ['1.1.1.1/32'], dry_run=False)


# main


def test_main_without_region_fails_cleanly(monkeypatch, capsys):
    for var in ('AWS_REGION', 'AWS_DEFAULT_REGION', 'AWS_PROFILE', 'AWS_CONFIG_FILE'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('AWS_CONFIG_FILE', '/nonexistent')
    monkeypatch.setattr(sys, 'argv', ['update_ip_sets.py', '--dry-run'])
    assert m.main() == 1
    assert 'no AWS region configured' in capsys.readouterr().err
