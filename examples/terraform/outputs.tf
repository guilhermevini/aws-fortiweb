output "web_acl_arn" {
  description = "ARN of the Web ACL."
  value       = aws_wafv2_web_acl.fortiweb_only.arn
}

output "ip_set_arns" {
  description = "ARNs of the referenced FortiWeb IP sets."
  value       = { for k, v in data.aws_wafv2_ip_set.fortiweb : k => v.arn }
}
