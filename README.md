# aws-fortiweb

[![CI](https://github.com/guilhermevini/aws-fortiweb/actions/workflows/ci.yml/badge.svg)](https://github.com/guilhermevini/aws-fortiweb/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Update FortiWeb IPs](https://github.com/guilhermevini/aws-fortiweb/actions/workflows/update-ips.yml/badge.svg)](https://github.com/guilhermevini/aws-fortiweb/actions/workflows/update-ips.yml)

Keep **AWS WAFv2 IP sets** in sync with the public IP ranges of **[FortiWeb Cloud](https://www.fortiweb-cloud.com)**, so that only FortiWeb can reach your AWS origin.

```
                ┌──────────────────┐        ┌───────────────────────────────┐
  Internet ───▶ │  FortiWeb Cloud  │ ─────▶ │ AWS WAF (allow FortiWeb IPs)  │ ───▶ ALB / API Gateway / CloudFront
                └──────────────────┘        └───────────────────────────────┘
   Attackers bypassing FortiWeb ───────────────────────▶ ✖ blocked
```

## Why?

FortiWeb Cloud is a WAF-as-a-Service: you point your DNS to it, it inspects the traffic and forwards clean requests to your origin. But your origin (for example, a public Application Load Balancer) still has a public DNS name and IPs. **Anyone who finds them can go straight to the origin and skip FortiWeb entirely.**

The fix is to accept traffic only from FortiWeb's IP addresses. FortiWeb publishes those lists, but they change over time. This project turns them into AWS WAF IP sets and keeps them updated.

## Features

- Downloads the official lists from `https://www.fortiweb-cloud.com/ips-v4` and `/ips-v6`
- Validates every CIDR, removes duplicates and sorts the result
- Creates the IP sets if they don't exist, updates them otherwise
- Prints a diff (`+` added / `-` removed) and supports `--dry-run`
- Handles `ListIPSets` pagination and retries on `WAFOptimisticLockException`
- Supports `REGIONAL` (ALB, API Gateway, AppSync, Cognito, App Runner…) and `CLOUDFRONT` scopes
- Exits with a non-zero code on failure, so it is safe to run from cron or CI
- Single dependency: `boto3`
- The IP lists in this repository ([`allowed_ips4.txt`](allowed_ips4.txt), [`allowed_ips6.txt`](allowed_ips6.txt)) are refreshed every week by a GitHub Action

## Installation

Every release on [GitHub Releases](https://github.com/guilhermevini/aws-fortiweb/releases) ships a wheel that pip can install straight from its URL. All options give you the same `aws-fortiweb` command.

**Server with Python and pip** (no git, no uv, no build step):

```bash
python3 -m pip install https://github.com/guilhermevini/aws-fortiweb/releases/download/v1.0.0/aws_fortiweb-1.0.0-py3-none-any.whl
```

Replace `1.0.0` with the [latest release](https://github.com/guilhermevini/aws-fortiweb/releases/latest). Other options:

| Environment | Install | Run |
| --- | --- | --- |
| Isolated CLI tool | `pipx install <wheel URL above>` | `aws-fortiweb` |
| [uv](https://docs.astral.sh/uv/) users (no install) | — | `uvx --from git+https://github.com/guilhermevini/aws-fortiweb@v1.0.0 aws-fortiweb` |
| No internet on the server | download the `.whl` elsewhere, copy it, then `pip install aws_fortiweb-*.whl` | `aws-fortiweb` |
| Single file, nothing else | `pip install boto3` (or `-r requirements.txt`) and copy [`aws_fortiweb.py`](aws_fortiweb.py) | `python3 aws_fortiweb.py` |

`python3 -m aws_fortiweb` also works whenever the package is installed (useful when `~/.local/bin` is not on your `PATH` after a `pip install --user`).

**Python 3.9+** is supported, so it runs on the default Python of Amazon Linux 2023, Ubuntu 22.04+ and Debian 12+. On Python 3.9, pip automatically installs the last `boto3` release that supports it; Python 3.10+ is recommended to keep receiving `boto3` updates.

## Quick start

```bash
python3 -m pip install https://github.com/guilhermevini/aws-fortiweb/releases/download/v1.0.0/aws_fortiweb-1.0.0-py3-none-any.whl

export AWS_PROFILE=my-profile
export AWS_REGION=us-east-1

aws-fortiweb --dry-run   # preview, read-only
aws-fortiweb             # apply
```

Example output:

```
$ aws-fortiweb
[IPv4] IP set 'FortiWeb-IPv4' not found; it will be created with 468 addresses.
[IPv4] IP set 'FortiWeb-IPv4' created.
[IPv6] IP set 'FortiWeb-IPv6' not found; it will be created with 312 addresses.
[IPv6] IP set 'FortiWeb-IPv6' created.

$ aws-fortiweb
[IPv4] IP set 'FortiWeb-IPv4' is already up to date (468 addresses).
[IPv6] IP set 'FortiWeb-IPv6': +2 / -1
  + 2600:1f18:1492:1702:524:eda4:749f:26d6/128
  + 2a05:d018:77c:d901:12e0:4d59:ac0d:cceb/128
  - 2600:1f14:b5a:da01:a32:4cac:f337:9c00/128
[IPv6] IP set 'FortiWeb-IPv6' updated.
```

## Usage

```
aws-fortiweb [--version {4,6,all}] [--source {url,file}]
             [--ipv4-file PATH] [--ipv6-file PATH]
             [--scope {REGIONAL,CLOUDFRONT}] [--region REGION]
             [--name-ipv4 NAME] [--name-ipv6 NAME] [--dry-run]
```

| Option | Default | Description |
| --- | --- | --- |
| `--version` | `all` | Sync only IPv4 (`4`), only IPv6 (`6`) or both |
| `--source` | `url` | `url` downloads the lists from FortiWeb; `file` reads local files |
| `--ipv4-file` / `--ipv6-file` | `allowed_ips4.txt` / `allowed_ips6.txt` | Files used with `--source file` (one CIDR per line, `#` comments allowed) |
| `--scope` | `REGIONAL` | `CLOUDFRONT` creates global IP sets (always in `us-east-1`) |
| `--region` | `AWS_REGION` / profile default | AWS region for `REGIONAL` IP sets |
| `--name-ipv4` | `FortiWeb-IPv4` | Name of the IPv4 IP set |
| `--name-ipv6` | `FortiWeb-IPv6` | Name of the IPv6 IP set |
| `--dry-run` | off | Show what would change without touching AWS |

`--source file` is handy when the server running the sync cannot reach `fortiweb-cloud.com`: fetch the lists elsewhere (or use the ones in this repository) and pass them in.

### Required IAM permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["wafv2:ListIPSets", "wafv2:GetIPSet", "wafv2:CreateIPSet", "wafv2:UpdateIPSet"],
    "Resource": "*"
  }]
}
```

## Use case: locking down an ALB behind FortiWeb Cloud

**Scenario:** your application runs on ECS/EKS/EC2 behind a public Application Load Balancer in `us-east-1`. You onboarded it to FortiWeb Cloud and changed your DNS (`app.example.com`) to FortiWeb. Now you want the ALB to reject any request that does not come through FortiWeb.

### 1. Create the IP sets

```bash
export AWS_REGION=us-east-1
aws-fortiweb
```

### 2. Create a Web ACL that only allows FortiWeb

Using the AWS CLI (or see the [Terraform example](#terraform) below):

```bash
IPV4_ARN=$(aws wafv2 list-ip-sets --scope REGIONAL \
  --query "IPSets[?Name=='FortiWeb-IPv4'].ARN" --output text)
IPV6_ARN=$(aws wafv2 list-ip-sets --scope REGIONAL \
  --query "IPSets[?Name=='FortiWeb-IPv6'].ARN" --output text)

cat > rules.json <<EOF
[{
  "Name": "allow-fortiweb",
  "Priority": 0,
  "Action": { "Allow": {} },
  "Statement": {
    "OrStatement": {
      "Statements": [
        { "IPSetReferenceStatement": { "ARN": "$IPV4_ARN" } },
        { "IPSetReferenceStatement": { "ARN": "$IPV6_ARN" } }
      ]
    }
  },
  "VisibilityConfig": {
    "SampledRequestsEnabled": true,
    "CloudWatchMetricsEnabled": true,
    "MetricName": "allow-fortiweb"
  }
}]
EOF

aws wafv2 create-web-acl \
  --name fortiweb-only \
  --scope REGIONAL \
  --default-action Block={} \
  --rules file://rules.json \
  --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName=fortiweb-only
```

> The rule matches the **source IP** of the connection, which is FortiWeb's address. Do not configure a forwarded-IP (`X-Forwarded-For`) setting on these IP set statements — that header contains the end user's IP, not FortiWeb's.

### 3. Attach the Web ACL to the ALB

```bash
WEB_ACL_ARN=$(aws wafv2 list-web-acls --scope REGIONAL \
  --query "WebACLs[?Name=='fortiweb-only'].ARN" --output text)

aws wafv2 associate-web-acl \
  --web-acl-arn "$WEB_ACL_ARN" \
  --resource-arn arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/abc123
```

### 4. Verify

```bash
curl -I https://app.example.com                         # through FortiWeb → 200
curl -I https://my-alb-123456.us-east-1.elb.amazonaws.com  # direct to the ALB → 403
```

### 5. Keep the IP sets updated

FortiWeb adds and removes IPs over time. A stale list will **block legitimate traffic** coming from new FortiWeb nodes, so schedule the sync. Two options:

**cron** (any machine with Python and AWS credentials, e.g. a small EC2 instance with an instance profile):

```cron
0 6 * * * AWS_REGION=us-east-1 /usr/local/bin/aws-fortiweb >> /var/log/aws-fortiweb.log 2>&1
```

Use `command -v aws-fortiweb` to find the right path (with `pip install --user` it is usually `~/.local/bin/aws-fortiweb`).

**GitHub Actions** with [OIDC](https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services) (no long-lived AWS keys):

```yaml
name: Sync FortiWeb IP sets

on:
  schedule:
    - cron: '0 6 * * *'
  workflow_dispatch:

permissions:
  id-token: write
  contents: read

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: '3.13'
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789012:role/fortiweb-ipset-sync
          aws-region: us-east-1
      - run: pip install https://github.com/guilhermevini/aws-fortiweb/releases/download/v1.0.0/aws_fortiweb-1.0.0-py3-none-any.whl
      - run: aws-fortiweb
```

The same approach works for **API Gateway** (REST API stages), **AppSync**, **Cognito** and **App Runner**. For **CloudFront**, use `--scope CLOUDFRONT` and create the Web ACL with `--scope CLOUDFRONT` in `us-east-1`.

## Terraform

[`examples/terraform`](examples/terraform) creates the "allow only FortiWeb" Web ACL and attaches it to your resources. The IP sets stay managed by `aws-fortiweb` and are only *referenced* by Terraform, so the two tools never fight over the address list.

```bash
aws-fortiweb                                   # 1. create/update the IP sets
cd examples/terraform
cp terraform.tfvars.example terraform.tfvars   # 2. set region and resource ARNs
terraform init && terraform apply              # 3. create the Web ACL and associations
```

Keep running `aws-fortiweb` on a schedule; Terraform does not need to be re-applied when the IPs change.

## Updating the lists in this repository

The [`Update FortiWeb IPs`](.github/workflows/update-ips.yml) workflow runs every Monday and commits any change to `allowed_ips4.txt` / `allowed_ips6.txt`. To refresh them locally:

```bash
./download_ips.sh
```

You can also use these files as a source for other tools (security groups, firewalls, Terraform `aws_wafv2_ip_set`, etc.), or sync from them with `aws-fortiweb --source file`.

## Development

The project uses [uv](https://docs.astral.sh/uv/) for dependencies, [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, [ty](https://docs.astral.sh/ty/) for type checking and [pytest](https://docs.pytest.org/) for tests. AWS calls are mocked with `botocore.Stubber`, so tests need no credentials.

```bash
uv sync                    # create .venv with runtime + dev dependencies
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run ty check            # type check
```

The [CI workflow](.github/workflows/ci.yml) runs all of the above (plus ShellCheck on `download_ips.sh`) on every push and pull request, testing Python 3.9 to 3.14. It also builds the package and installs it with plain `pip` (no uv) to make sure the pip-only path keeps working, and validates the Terraform example. Dependabot keeps GitHub Actions and Python dependencies up to date.

## Contributing

Issues and pull requests are welcome. Please make sure `uv run pytest`, `uv run ruff check .` and `uv run ty check` pass. Ideas for contributions:

- CloudFormation / CDK examples
- An AWS Lambda + EventBridge deployment
- Support for updating security groups or managed prefix lists

## Releasing

1. Bump `__version__` in [`aws_fortiweb.py`](aws_fortiweb.py), update the version in the install URLs of this README, and merge to `main`.
2. Tag and push: `git tag v1.2.3 && git push origin v1.2.3`.

The [Release workflow](.github/workflows/release.yml) checks that the tag matches `__version__`, runs the tests, builds the sdist and wheel and creates a GitHub release with both attached.

Publishing to PyPI is opt-in: configure a [trusted publisher](https://docs.pypi.org/trusted-publishers/) on PyPI (workflow `release.yml`, environment `pypi`) and set the repository variable `PUBLISH_TO_PYPI=true`. No API token is stored in GitHub.

## Disclaimer

This is a community project and is not affiliated with, endorsed by, or supported by Fortinet or Amazon Web Services. The IP lists are fetched from FortiWeb Cloud's public endpoints; always confirm the current ranges in the official FortiWeb Cloud documentation.

## License

[MIT](LICENSE) — free to use, modify and distribute, including for commercial purposes.
