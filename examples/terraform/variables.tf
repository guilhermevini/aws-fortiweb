variable "region" {
  description = "AWS region of the protected resources and of the IP sets."
  type        = string
  default     = "us-east-1"
}

variable "web_acl_name" {
  description = "Name of the Web ACL."
  type        = string
  default     = "fortiweb-only"
}

variable "ip_set_names" {
  description = "Names of the IP sets created by aws-fortiweb (--name-ipv4 / --name-ipv6)."
  type = object({
    ipv4 = string
    ipv6 = string
  })
  default = {
    ipv4 = "FortiWeb-IPv4"
    ipv6 = "FortiWeb-IPv6"
  }
}

variable "resource_arns" {
  description = "ARNs of the resources to protect (ALB, API Gateway stage, AppSync API, Cognito user pool, App Runner service...)."
  type        = list(string)
  default     = []
}
