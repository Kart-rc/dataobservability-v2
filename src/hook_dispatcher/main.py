import boto3
import json
import logging
import os
import time
import ulid
from datetime import datetime, timezone
import glob

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("hook_dispatcher")

# Environment vars
ENDPOINT_URL = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION_NAME = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "test")

# Simulate S3 by reading local directory if not using boto3 for Delta Log
# In this mock, we actually look at a local folder mapped to `/tmp/s3_local`
DATA_LAKE_PATH = "/tmp/s3_local"

def get_sqs_client():
    return boto3.client(
        'sqs',
        endpoint_url=ENDPOINT_URL,
        region_name=REGION_NAME,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

def get_dynamo_client():
    return boto3.client(
        'dynamodb',
        endpoint_url=ENDPOINT_URL,
        region_name=REGION_NAME,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )


class MockDeltaPoller:
    """Mock Delta commit log poller that watches a local directory."""
    def __init__(self, table_path, dataset_urn):
        self.table_path = table_path
        self.dataset_urn = dataset_urn
        self.dynamodb = get_dynamo_client()
        self.sqs = get_sqs_client()
        try:
            queue_name = "signal-factory-validation-requests.fifo"
            self.queue_url = self.sqs.get_queue_url(QueueName=queue_name)['QueueUrl']
        except Exception as e:
            logger.error(f"Failed to get queue URL: {e}")
            self.queue_url = None

    def get_last_processed_version(self):
        try:
            response = self.dynamodb.get_item(
                TableName="HookState",
                Key={"dataset_urn": {"S": self.dataset_urn}}
            )
            if 'Item' in response:
                return int(response['Item']['last_processed_version']['N'])
        except Exception as e:
            logger.error(f"Error fetching state: {e}")
        return -1

    def set_last_processed_version(self, version):
        try:
            self.dynamodb.put_item(
                TableName="HookState",
                Item={
                    "dataset_urn": {"S": self.dataset_urn},
                    "last_processed_version": {"N": str(version)},
                    "updated_at": {"S": datetime.now(timezone.utc).isoformat()}
                }
            )
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def is_duplicate(self, request_id):
        try:
            self.dynamodb.put_item(
                TableName="HookDeduplication",
                Item={
                    "request_id": {"S": request_id},
                    "created_at": {"N": str(int(time.time()))},
                },
                ConditionExpression="attribute_not_exists(request_id)",
            )
            return False
        except self.dynamodb.exceptions.ConditionalCheckFailedException:
            return True
        except Exception as e:
            logger.error(f"Error deduplicating: {e}")
            return False

    def get_latest_commits(self):
        # Look for JSON files in _delta_log
        log_dir = os.path.join(self.table_path, "_delta_log")
        if not os.path.exists(log_dir):
            return []
            
        commits = []
        for file in os.listdir(log_dir):
            if file.endswith(".json"):
                version = int(file.replace(".json", ""))
                commits.append((version, os.path.join(log_dir, file)))
        return sorted(commits, key=lambda x: x[0])

    def parse_commit(self, file_path):
        commit_data = {"commitInfo": {}}
        add_actions = []
        with open(file_path, 'r') as f:
            for line in f:
                data = json.loads(line)
                if "commitInfo" in data:
                    commit_data["commitInfo"] = data["commitInfo"]
                elif "add" in data:
                    add_actions.append(data["add"])
        
        return commit_data, add_actions

    def create_request(self, version, commit_info, add_actions):
        dataset_urn = self.dataset_urn
        request_id = f"vr-{str(ulid.new())}"
        
        # Simplified validation request payload
        payload = {
            "request_id": request_id,
            "dataset_urn": dataset_urn,
            "storage_type": "delta",
            "table_path": self.table_path,
            "commit_version": version,
            "timestamp": datetime.fromtimestamp(commit_info.get("timestamp", int(time.time() * 1000)) / 1000, tz=timezone.utc).isoformat(),
            "operation": commit_info.get("operation", "WRITE"),
            "num_files": len(add_actions),
            "correlation_id": commit_info.get("txnId", "")
        }
        return payload

    def enqueue(self, payload):
        if not self.queue_url:
            logger.error("Queue URL not initialized, cannot enqueue.")
            return

        if self.is_duplicate(payload["request_id"]):
            logger.info(f"Duplicate request detected: {payload['request_id']}")
            return

        logger.info(f"Enqueuing: {payload['dataset_urn']} version {payload['commit_version']}")
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(payload),
            MessageGroupId=payload["dataset_urn"],
            MessageDeduplicationId=payload["request_id"]
        )

    def poll(self):
        last_version = self.get_last_processed_version()
        commits = self.get_latest_commits()
        
        for version, file_path in commits:
            if version > last_version:
                logger.info(f"Found new commit version {version}")
                commit_info, add_actions = self.parse_commit(file_path)
                req = self.create_request(version, commit_info, add_actions)
                self.enqueue(req)
                self.set_last_processed_version(version)


def run_forever():
    """Poll continuously, mimicking a scheduled lambda mapping over tables."""
    logger.info("Starting Hook Dispatcher Poller...")
    time.sleep(10) # Wait for localstack to start and scripts/setup_local_infra.py to run

    # Suppose we track 1 table locally
    poller = MockDeltaPoller(
        table_path=os.path.join(DATA_LAKE_PATH, "gold", "_staging", "orders"),
        dataset_urn="ds://curated/orders_enriched"
    )

    while True:
        try:
            poller.poll()
        except Exception as e:
            logger.error(f"Poller error: {e}")
        time.sleep(15)

if __name__ == "__main__":
    run_forever()
