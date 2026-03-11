terraform {
  required_version = ">= 1.6.0"
}

variable "image" {
  type    = string
  default = "ghcr.io/example/algo-platform:latest"
}

resource "null_resource" "notes" {
  triggers = {
    image = var.image
  }
}

output "deployment_note" {
  value = "Replace this scaffold with your cloud-specific ECS, GKE, AKS, or Kubernetes manifests."
}
