# aws-fortiweb

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
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

## Quick start

```bash
git clone https://github.com/guilhermevini/aws-fortiweb.git
cd aws-fortiweb
pip install -r requirements.txt

export AWS_PROFILE=my-profile
export AWS_REGION=us-east-1

python update_ip_sets.py --dry-run   # preview
python update_ip_sets.py             # apply
```

Example output:

```
[IPv4] IP set 'FortiWeb-IPv4' not found; it will be created with 468 addresses.
[IPv4] IP set 'FortiWeb-IPv4' created.
[IPv6] IP set 'FortiWeb-IPv6': +3 / -1
  + 2600:1f14:b5a:da01::/64
  + 2a05:d018:abc::/48
  + 2a05:d018:def::/48
  - 2600:1f14:dead:beef::/64
[IPv6] IP set 'FortiWeb-IPv6' updated.
```

## Usage

```
python update_ip_sets.py [--version {4,6,all}] [--source {url,file}]
                         [--scope {REGIONAL,CLOUDFRONT}] [--region REGION]
                         [--name-ipv4 NAME] [--name-ipv6 NAME] [--dry-run]
```

| Option | Default | Description |
| --- | --- | --- |
| `--version` | `all` | Sync only IPv4 (`4`), only IPv6 (`6`) or both |
| `--source` | `url` | `url` downloads the lists from FortiWeb; `file` uses the `.txt` files in this repo |
| `--scope` | `REGIONAL` | `CLOUDFRONT` creates global IP sets (always in `us-east-1`) |
| `--region` | `AWS_REGION` / profile default | AWS region for `REGIONAL` IP sets |
| `--name-ipv4` | `FortiWeb-IPv4` | Name of the IPv4 IP set |
| `--name-ipv6` | `FortiWeb-IPv6` | Name of the IPv6 IP set |
| `--dry-run` | off | Show what would change without touching AWS |

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
python update_ip_sets.py
```

### 2. Create a Web ACL that only allows FortiWeb

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

**cron** (any machine with AWS credentials):

```cron
0 6 * * * cd /opt/aws-fortiweb && python3 update_ip_sets.py >> /var/log/aws-fortiweb.log 2>&1
```

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
      - uses: actions/checkout@v4
        with:
          repository: guilhermevini/aws-fortiweb
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789012:role/fortiweb-ipset-sync
          aws-region: us-east-1
      - run: pip install -r requirements.txt
      - run: python update_ip_sets.py
```

The same approach works for **API Gateway** (REST API stages), **AppSync**, **Cognito** and **App Runner**. For **CloudFront**, use `--scope CLOUDFRONT` and create the Web ACL with `--scope CLOUDFRONT` in `us-east-1`.

## Updating the lists in this repository

The [`Update FortiWeb IPs`](.github/workflows/update-ips.yml) workflow runs every Monday and commits any change to `allowed_ips4.txt` / `allowed_ips6.txt`. To refresh them locally:

```bash
./download_ips.sh
```

You can also use these files as a source for other tools (security groups, firewalls, Terraform `aws_wafv2_ip_set`, etc.), or sync from them with `python update_ip_sets.py --source file`.

## Contributing

Issues and pull requests are welcome. Ideas for contributions:

- Terraform / CloudFormation / CDK examples
- An AWS Lambda + EventBridge deployment
- Support for updating security groups or managed prefix lists

## Disclaimer

This is a community project and is not affiliated with, endorsed by, or supported by Fortinet or Amazon Web Services. The IP lists are fetched from FortiWeb Cloud's public endpoints; always confirm the current ranges in the official FortiWeb Cloud documentation.

## License

[MIT](LICENSE) — free to use, modify and distribute, including for commercial purposes.
