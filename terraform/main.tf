terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.aws_region }

module "vpc" {
  source               = "terraform-aws-modules/vpc/aws"
  version              = "5.0.0"
  name                 = "${var.project_name}-vpc"
  cidr                 = var.vpc_cidr
  azs                  = var.availability_zones
  private_subnets      = var.private_subnet_cidrs
  public_subnets       = var.public_subnet_cidrs
  enable_nat_gateway   = true
  single_nat_gateway   = true
  enable_dns_hostnames = true
  enable_dns_support   = true
  public_subnet_tags  = {
    "kubernetes.io/role/elb"                            = "1"
    "kubernetes.io/cluster/${var.project_name}-cluster" = "shared"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"                   = "1"
    "kubernetes.io/cluster/${var.project_name}-cluster" = "shared"
  }
  tags = { Project = var.project_name, ManagedBy = "Terraform" }
}

module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  version         = "19.21.0"
  cluster_name    = "${var.project_name}-cluster"
  cluster_version = "1.29"
  cluster_endpoint_public_access  = true
  create_cloudwatch_log_group     = false
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnets
  eks_managed_node_groups = {
    infragpt_nodes = {
      instance_types = ["t3.medium"]
      min_size       = 1
      max_size       = 3
      desired_size   = 2
    }
  }
  tags = { Project = var.project_name, ManagedBy = "Terraform" }
}

# EBS CSI Driver — allows K8s to provision EBS volumes for PVCs
resource "aws_eks_addon" "ebs_csi" {
  cluster_name = module.eks.cluster_name
  addon_name   = "aws-ebs-csi-driver"
  depends_on   = [module.eks]
}

# IAM Policy — node role needs this to create/attach EBS volumes
resource "aws_iam_role_policy_attachment" "ebs_csi_policy" {
  role       = module.eks.eks_managed_node_groups["infragpt_nodes"].iam_role_name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

output "cluster_name"      { value = module.eks.cluster_name }
output "cluster_endpoint"  { value = module.eks.cluster_endpoint }
output "configure_kubectl" {
  value = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}
