# Web ACL that only allows traffic coming from FortiWeb Cloud.
#
# The IP sets themselves are managed by aws-fortiweb (run it before `terraform apply`
# and on a schedule afterwards). Terraform only references them, so the two tools
# never fight over the address list.

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

data "aws_wafv2_ip_set" "fortiweb" {
  for_each = var.ip_set_names

  name  = each.value
  scope = "REGIONAL"
}

resource "aws_wafv2_web_acl" "fortiweb_only" {
  name        = var.web_acl_name
  description = "Allow only FortiWeb Cloud - managed by Terraform"
  scope       = "REGIONAL"

  default_action {
    block {}
  }

  rule {
    name     = "allow-fortiweb"
    priority = 0

    action {
      allow {}
    }

    statement {
      or_statement {
        statement {
          ip_set_reference_statement {
            arn = data.aws_wafv2_ip_set.fortiweb["ipv4"].arn
          }
        }
        statement {
          ip_set_reference_statement {
            arn = data.aws_wafv2_ip_set.fortiweb["ipv6"].arn
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "allow-fortiweb"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = var.web_acl_name
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "this" {
  for_each = toset(var.resource_arns)

  resource_arn = each.value
  web_acl_arn  = aws_wafv2_web_acl.fortiweb_only.arn
}
