import boto3
import json
import logging
import os
import time
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("setup_local_infra")

# Environment vars
ENDPOINT_URL = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION_NAME = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "test")

def get_client(service_name):
    return boto3.client(
        service_name,
        endpoint_url=ENDPOINT_URL,
        region_name=REGION_NAME,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

def setup_sqs():
    sqs = get_client('sqs')
    
    # Validation Requests Queue
    queue_name = "signal-factory-validation-requests.fifo"
    dlq_name = "signal-factory-validation-requests-dlq.fifo"
    
    try:
        # Create DLQ
        dlq_response = sqs.create_queue(
            QueueName=dlq_name,
            Attributes={
                "FifoQueue": "true",
                "MessageRetentionPeriod": "1209600" # 14 days
            }
        )
        dlq_arn = sqs.get_queue_attributes(
            QueueUrl=dlq_response['QueueUrl'],
            AttributeNames=['QueueArn']
        )['Attributes']['QueueArn']
        logger.info(f"Created DLQ: {dlq_name} (ARN: {dlq_arn})")

        # Create Main Queue
        response = sqs.create_queue(
            QueueName=queue_name,
            Attributes={
                "FifoQueue": "true",
                "ContentBasedDeduplication": "false",
                "VisibilityTimeout": "60", # Short for local testing
                "MessageRetentionPeriod": "86400",
                "ReceiveMessageWaitTimeSeconds": "2",
                "RedrivePolicy": json.dumps({
                    "deadLetterTargetArn": dlq_arn,
                    "maxReceiveCount": 3
                })
            }
        )
        logger.info(f"Created Main Queue: {queue_name} (URL: {response['QueueUrl']})")
    
    except Exception as e:
        logger.error(f"Error creating SQS queues: {e}")

def setup_dynamodb():
    dynamodb = get_client('dynamodb')
    
    tables = [
        {
            "TableName": "HookState",
            "KeySchema": [{"AttributeName": "dataset_urn", "KeyType": "HASH"}],
            "AttributeDefinitions": [{"AttributeName": "dataset_urn", "AttributeType": "S"}],
            "BillingMode": "PAY_PER_REQUEST"
        },
        {
            "TableName": "HookDeduplication",
            "KeySchema": [{"AttributeName": "request_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [{"AttributeName": "request_id", "AttributeType": "S"}],
            "BillingMode": "PAY_PER_REQUEST"
        },
    ]

    for table in tables:
        try:
            dynamodb.create_table(**table)
            logger.info(f"Created DynamoDB Table: {table['TableName']}")
        except dynamodb.exceptions.ResourceInUseException:
            logger.info(f"DynamoDB Table {table['TableName']} already exists.")
        except Exception as e:
            logger.error(f"Error creating DynamoDB Table {table['TableName']}: {e}")

def setup_s3():
    s3 = get_client('s3')
    bucket_name = "data-lake"
    
    try:
        s3.create_bucket(Bucket=bucket_name)
        logger.info(f"Created S3 Bucket: {bucket_name}")
    except s3.exceptions.BucketAlreadyExists:
        logger.info(f"S3 Bucket {bucket_name} already exists.")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        logger.info(f"S3 Bucket {bucket_name} already owned by you.")
    except Exception as e:
        logger.error(f"Error creating S3 Bucket: {e}")

if __name__ == "__main__":
    logger.info("Initializing Local AWS Infrastructure...")
    setup_sqs()
    setup_dynamodb()
    setup_s3()
    logger.info("Local infrastructure setup complete.")
