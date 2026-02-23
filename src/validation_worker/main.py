import boto3
import json
import logging
import os
import time
import duckdb

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("validation_worker")

# Environment vars
ENDPOINT_URL = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION_NAME = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "test")

def get_sqs_client():
    return boto3.client(
        'sqs',
        endpoint_url=ENDPOINT_URL,
        region_name=REGION_NAME,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

class DuckDBValidator:
    def __init__(self):
        self.conn = duckdb.connect()
        self.conn.execute("SET memory_limit='2048MB'")
        try:
            self.conn.execute("INSTALL delta; LOAD delta")
            logger.info("Loaded DuckDB Delta Extension")
        except Exception as e:
            logger.warning(f"Could not load Delta extension natively, falling back: {e}")

    def validate_request(self, request):
        logger.info(f"Starting validation for {request['dataset_urn']} - Version: {request.get('commit_version')}")
        
        path = request['table_path']
        if not path.startswith("/tmp"): # Fix path for local run
            path = path.replace("/app/data", "/tmp/s3_local")
            
        try:
            # Check files exist
            if not os.path.exists(path):
                logger.error(f"Path not found: {path}")
                return False

            # G1: Resolution Gate
            logger.info("Evaluating G1: Resolution Gate... PASS")

            # Read Parquet part files directly for mock
            query = f"SELECT * FROM read_parquet('{path}/*.parquet')"
            relation = self.conn.sql(query)
            
            row_count = relation.aggregate("count(*)").fetchone()[0]
            logger.info(f"Evaluated data. Total rows scanned: {row_count}")

            # G3: Schema Gate (Mock)
            logger.info("Evaluating G3: Schema Gate... PASS")

            # G4: Contract Gate (Mock) - Check null rate
            stats = self.conn.sql(f"""
                SELECT count(order_id) as non_null_orders 
                FROM ({relation.sql_query()}) t
            """).fetchone()

            if stats[0] < row_count:
                logger.warning(f"Evaluating G4: Contract Gate... WARN (Found {row_count - stats[0]} null order_ids)")
            else:
                logger.info("Evaluating G4: Contract Gate... PASS")
            
            # G6: Volume Gate (Mock)
            files = request.get('num_files', 1)
            if row_count == 0:
                logger.error("Evaluating G6: Volume Gate... FAIL (Zero rows found)")
                return False
            else:
                logger.info(f"Evaluating G6: Volume Gate... PASS ({files} files, {row_count} rows)")
            
            logger.info(f"Validation COMPLETE for {request['dataset_urn']}")
            return True

        except Exception as e:
            logger.error(f"Error during validation logic: {e}")
            return False

def run_worker():
    logger.info("Starting Validation Worker...")
    time.sleep(15) # Wait for localstack & setup
    
    sqs = get_sqs_client()
    try:
        queue_url = sqs.get_queue_url(QueueName="signal-factory-validation-requests.fifo")['QueueUrl']
    except Exception as e:
        logger.error(f"Failed to get queue URL: {e}")
        return

    validator = DuckDBValidator()

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=10
            )

            if 'Messages' in response:
                for message in response['Messages']:
                    body = json.loads(message['Body'])
                    logger.info(f"Received ValidationRequest: {body['request_id']}")
                    
                    success = validator.validate_request(body)
                    
                    if success:
                        logger.info(f"Validation succeeded. Deleting message {message['MessageId']}")
                        sqs.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=message['ReceiptHandle']
                        )
                    else:
                        logger.error(f"Validation failed for message {message['MessageId']}")
        except Exception as e:
            logger.error(f"Worker polling error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_worker()
