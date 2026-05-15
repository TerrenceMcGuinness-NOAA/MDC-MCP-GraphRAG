#!/usr/bin/env python3
"""
SageMaker Job Launcher — Submit ingestion scripts as SageMaker Processing Jobs

Offloads compute-intensive embedding generation to SageMaker, keeping the
development EC2 instance free. Supports GPU instances for large models.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, Optional

import boto3
from botocore.exceptions import ClientError


class SageMakerJobLauncher:
    """Submits ingestion scripts as SageMaker Processing Jobs."""
    
    INSTANCE_PRICING = {
        'ml.m5.large': 0.115,
        'ml.m5.xlarge': 0.230,
        'ml.m5.2xlarge': 0.460,
        'ml.g5.xlarge': 1.006,
        'ml.g5.2xlarge': 1.515,
    }
    
    def __init__(self, region: str = None):
        self.region = region or os.environ.get('AWS_REGION', 'us-east-1')
        self.sm = boto3.client('sagemaker', region_name=self.region)
        self.ecr_image = os.environ.get('SAGEMAKER_ECR_IMAGE', 
                                        f'{self._get_account_id()}.dkr.ecr.{self.region}.amazonaws.com/mdc-mcp-rag-ingestion:latest')
        self.role_arn = os.environ.get('SAGEMAKER_ROLE_ARN')
        if not self.role_arn:
            raise ValueError("SAGEMAKER_ROLE_ARN env var required")
    
    def _get_account_id(self) -> str:
        return boto3.client('sts').get_caller_identity()['Account']
    
    def submit(self, script: str, instance_type: str = 'ml.m5.large',
               model: str = 'mpnet768', backend: str = 'aws',
               collections: Optional[str] = None, dry_run: bool = False) -> str:
        """
        Submit a SageMaker Processing Job.
        
        Args:
            script: Ingestion script name (e.g., "ingest_code_v8.py")
            instance_type: SageMaker instance type
            model: Model short name from registry
            backend: "aws" or "legacy"
            collections: Comma-separated collection names (optional)
            dry_run: If True, only estimate cost without submitting
        
        Returns:
            Job name for tracking
        """
        job_name = f"mdc-ingest-{script.replace('.py', '')}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        if dry_run:
            cost = self.estimate_cost(instance_type, estimated_minutes=60)
            print(f"[DRY-RUN] Would submit job: {job_name}")
            print(f"[DRY-RUN] Estimated cost: ${cost['estimated_cost']:.2f} for {cost['estimated_minutes']} minutes")
            return job_name
        
        args = [
            'python3', f'/opt/ml/processing/input/{script}',
            '--model', model,
            '--backend', backend
        ]
        if collections:
            args.extend(['--collections', collections])
        
        try:
            self.sm.create_processing_job(
                ProcessingJobName=job_name,
                RoleArn=self.role_arn,
                AppSpecification={
                    'ImageUri': self.ecr_image,
                    'ContainerEntrypoint': args
                },
                ProcessingResources={
                    'ClusterConfig': {
                        'InstanceCount': 1,
                        'InstanceType': instance_type,
                        'VolumeSizeInGB': 30
                    }
                },
                StoppingCondition={'MaxRuntimeInSeconds': 86400}
            )
            print(f"[OK] Submitted SageMaker job: {job_name}")
            return job_name
        except ClientError as e:
            print(f"[ERROR] Failed to submit job: {e}", file=sys.stderr)
            raise
    
    def estimate_cost(self, instance_type: str, estimated_minutes: int) -> Dict:
        """Estimate job cost without submitting."""
        hourly_rate = self.INSTANCE_PRICING.get(instance_type, 0.0)
        estimated_cost = (hourly_rate / 60) * estimated_minutes
        return {
            'instance_type': instance_type,
            'hourly_rate': hourly_rate,
            'estimated_minutes': estimated_minutes,
            'estimated_cost': estimated_cost
        }
    
    def get_job_status(self, job_name: str) -> Dict:
        """Poll job status, return counts and errors."""
        try:
            response = self.sm.describe_processing_job(ProcessingJobName=job_name)
            return {
                'job_name': job_name,
                'status': response['ProcessingJobStatus'],
                'failure_reason': response.get('FailureReason'),
                'creation_time': response['CreationTime'].isoformat(),
                'last_modified_time': response['LastModifiedTime'].isoformat()
            }
        except ClientError as e:
            return {'job_name': job_name, 'error': str(e)}


def main():
    parser = argparse.ArgumentParser(description='Submit ingestion scripts to SageMaker')
    parser.add_argument('script', help='Ingestion script name (e.g., ingest_code_v8.py)')
    parser.add_argument('--instance-type', default='ml.m5.large', help='SageMaker instance type')
    parser.add_argument('--model', default='mpnet768', help='Model short name')
    parser.add_argument('--backend', default='aws', choices=['aws', 'legacy'])
    parser.add_argument('--collections', help='Comma-separated collection names')
    parser.add_argument('--dry-run', action='store_true', help='Estimate cost without submitting')
    parser.add_argument('--status', help='Check status of existing job')
    
    args = parser.parse_args()
    launcher = SageMakerJobLauncher()
    
    if args.status:
        status = launcher.get_job_status(args.status)
        print(json.dumps(status, indent=2))
    else:
        job_name = launcher.submit(
            args.script,
            instance_type=args.instance_type,
            model=args.model,
            backend=args.backend,
            collections=args.collections,
            dry_run=args.dry_run
        )
        if not args.dry_run:
            print(f"Track job status: python3 {__file__} --status {job_name}")


if __name__ == '__main__':
    main()
