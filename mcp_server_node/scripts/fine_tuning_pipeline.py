#!/usr/bin/env python3
"""
Fine-Tuning Pipeline — Domain-adaptive fine-tuning using Sentence Transformers

Generates training pairs from existing collections, submits SageMaker Training Jobs,
and registers fine-tuned models in the embedding registry.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple

import boto3
from botocore.exceptions import ClientError

from embedding_registry import EmbeddingModelRegistry, ModelProfile


@dataclass
class TrainingPair:
    anchor: str
    positive: str
    negative: str


class FineTuningPipeline:
    """Domain-adaptive fine-tuning using Sentence Transformers v3+ Trainer."""
    
    def __init__(self):
        self.sm = boto3.client('sagemaker', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        self.s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        self.registry = EmbeddingModelRegistry()
        self.role_arn = os.environ.get('SAGEMAKER_ROLE_ARN')
        if not self.role_arn:
            raise ValueError("SAGEMAKER_ROLE_ARN env var required")
    
    def generate_training_pairs(self, collection_name: str, 
                                 feedback_log_path: str = None) -> List[TrainingPair]:
        """
        Auto-generate positive pairs (same-section) and hard negatives.
        
        Args:
            collection_name: Collection to generate pairs from
            feedback_log_path: Optional S3 path to feedback log for additional training data
        
        Returns:
            List of TrainingPair objects
        """
        # Placeholder: would query vector DB and graph DB to generate pairs
        # Positive pairs: documents from same section/module
        # Hard negatives: from hard_negative_miner.py
        pairs = []
        
        if feedback_log_path:
            pairs.extend(self._extract_pairs_from_feedback(feedback_log_path))
        
        return pairs
    
    def train(self, base_model: str, training_data: List[TrainingPair],
              output_s3_path: str, instance_type: str = 'ml.g5.xlarge') -> str:
        """
        Submit SageMaker Training Job. Returns model artifact S3 path.
        
        Args:
            base_model: Base model short name or HuggingFace model ID
            training_data: List of training pairs
            output_s3_path: S3 path for model artifacts
            instance_type: SageMaker instance type
        
        Returns:
            S3 path to trained model artifacts
        """
        job_name = f"mdc-finetune-{base_model.replace('/', '-')}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        # Upload training data to S3
        training_s3_path = self._upload_training_data(training_data, job_name)
        
        try:
            self.sm.create_training_job(
                TrainingJobName=job_name,
                RoleArn=self.role_arn,
                AlgorithmSpecification={
                    'TrainingImage': self._get_training_image(),
                    'TrainingInputMode': 'File'
                },
                InputDataConfig=[{
                    'ChannelName': 'training',
                    'DataSource': {
                        'S3DataSource': {
                            'S3DataType': 'S3Prefix',
                            'S3Uri': training_s3_path,
                            'S3DataDistributionType': 'FullyReplicated'
                        }
                    }
                }],
                OutputDataConfig={'S3OutputPath': output_s3_path},
                ResourceConfig={
                    'InstanceType': instance_type,
                    'InstanceCount': 1,
                    'VolumeSizeInGB': 30
                },
                StoppingCondition={'MaxRuntimeInSeconds': 86400},
                HyperParameters={
                    'base_model': base_model,
                    'epochs': '3',
                    'batch_size': '16',
                    'learning_rate': '2e-5'
                }
            )
            print(f"[OK] Submitted training job: {job_name}")
            return f"{output_s3_path}/{job_name}/output/model.tar.gz"
        except ClientError as e:
            print(f"[ERROR] Failed to submit training job: {e}", file=sys.stderr)
            raise
    
    def register_model(self, model_s3_path: str, short_name: str) -> ModelProfile:
        """Register fine-tuned model in EmbeddingModelRegistry."""
        profile = ModelProfile(
            short_name=short_name,
            provider='local',
            model_id=model_s3_path,
            dimensions=768,  # Would be detected from model config
            supports_matryoshka=False,
            supports_multimodal=False
        )
        self.registry.register(profile)
        print(f"[OK] Registered fine-tuned model: {short_name}")
        return profile
    
    def _extract_pairs_from_feedback(self, feedback_log_path: str) -> List[TrainingPair]:
        """Extract training pairs from feedback log."""
        # Placeholder: would parse feedback log and generate pairs
        return []
    
    def _upload_training_data(self, training_data: List[TrainingPair], job_name: str) -> str:
        """Upload training data to S3 in JSONL format."""
        bucket = os.environ.get('TRAINING_DATA_BUCKET', 'mdc-mcp-rag-training-data')
        key = f"training-data/{job_name}/pairs.jsonl"
        
        lines = [json.dumps({'anchor': p.anchor, 'positive': p.positive, 'negative': p.negative}) 
                 for p in training_data]
        body = '\n'.join(lines)
        
        self.s3.put_object(Bucket=bucket, Key=key, Body=body)
        return f"s3://{bucket}/training-data/{job_name}/"
    
    def _get_training_image(self) -> str:
        """Get SageMaker training container image URI."""
        account_id = boto3.client('sts').get_caller_identity()['Account']
        region = os.environ.get('AWS_REGION', 'us-east-1')
        return f"{account_id}.dkr.ecr.{region}.amazonaws.com/mdc-mcp-rag-training:latest"


def main():
    parser = argparse.ArgumentParser(description='Fine-tune embedding models')
    parser.add_argument('--base-model', required=True, help='Base model short name')
    parser.add_argument('--collection', required=True, help='Collection to train on')
    parser.add_argument('--feedback-log', help='S3 path to feedback log')
    parser.add_argument('--output-s3', required=True, help='S3 output path')
    parser.add_argument('--instance-type', default='ml.g5.xlarge')
    parser.add_argument('--register-as', help='Short name for fine-tuned model')
    
    args = parser.parse_args()
    pipeline = FineTuningPipeline()
    
    print(f"[INFO] Generating training pairs from {args.collection}...")
    training_data = pipeline.generate_training_pairs(args.collection, args.feedback_log)
    print(f"[OK] Generated {len(training_data)} training pairs")
    
    print(f"[INFO] Submitting training job...")
    model_path = pipeline.train(args.base_model, training_data, args.output_s3, args.instance_type)
    print(f"[OK] Model will be saved to: {model_path}")
    
    if args.register_as:
        pipeline.register_model(model_path, args.register_as)


if __name__ == '__main__':
    main()
