import duckdb
import os
from datetime import datetime
import time

DATA_LAKE_PATH = "/tmp/s3_local"
TABLE_PATH = os.path.join(DATA_LAKE_PATH, "gold", "_staging", "orders")

def generate_delta_data():
    print(f"Generating simulated Delta Lake table at {TABLE_PATH}...")
    
    # Ensure dir exists
    os.makedirs(TABLE_PATH, exist_ok=True)
    
    conn = duckdb.connect()
    
    # Enable delta extension (Not needed for manual log generation)
    # conn.execute("INSTALL delta; LOAD delta")

    # Generate some mock data
    print("Creating and inserting 1,000,000 rows into Delta table...")
    conn.execute(f"""
        CREATE OR REPLACE TABLE mock_orders AS
        SELECT 
            range as order_id, 
            uuid() as customer_id, 
            cast((range % 1000) + 10 as decimal(10,2)) as amount,
            (TIMESTAMP '2026-02-15 00:00:00' + 
             INTERVAL (range % 100) MINUTE) as order_time
        FROM range(1000000);
    """)

    # We use community Delta writer which is limited in DuckDB natively to Parquet output then Delta Log generation 
    # Actually, recent duckdb versions can write directly if "CREATE TABLE ... USING delta" is not available, we can just write parquet files and mock a Delta log commit manually...
    # BUT wait, duckdb can do 'COPY mock_orders TO 'path' (FORMAT PARQUET)'. Let's just create raw Parquet and fake a Delta log!
    
    conn.execute(f"COPY mock_orders TO '{TABLE_PATH}/part-0000.parquet' (FORMAT PARQUET)")
    
    # Mocking Delta _delta_log
    log_dir = os.path.join(TABLE_PATH, "_delta_log")
    os.makedirs(log_dir, exist_ok=True)
    
    file_size = os.path.getsize(f"{TABLE_PATH}/part-0000.parquet")
    
    commit_data = {
        "commitInfo": {
            "timestamp": int(time.time() * 1000),
            "operation": "WRITE",
            "operationParameters": {"mode": "Overwrite"},
            "engineInfo": "Apache-Spark/3.5.1",
            "operationMetrics": {
                "numFiles": "1",
                "numOutputRows": "1000000",
                "numOutputBytes": str(file_size)
            }
        }
    }
    
    add_action = {
        "add": {
            "path": "part-0000.parquet",
            "size": file_size,
            "partitionValues": {},
            "modificationTime": int(time.time() * 1000),
            "dataChange": True,
            "stats": "{\"numRecords\":1000000}"
        }
    }
    
    # Write version 0
    with open(os.path.join(log_dir, "00000000000000000000.json"), "w") as f:
        f.write(json.dumps({"protocol": {"minReaderVersion": 1, "minWriterVersion": 2}}) + "\n")
        f.write(json.dumps({"metaData": {"id": "test-id", "format": {"provider": "parquet"}, "schemaString": "{\"type\":\"struct\",\"fields\":[{\"name\":\"order_id\",\"type\":\"long\",\"nullable\":true,\"metadata\":{}},{\"name\":\"customer_id\",\"type\":\"string\",\"nullable\":true,\"metadata\":{}},{\"name\":\"amount\",\"type\":\"decimal(10,2)\",\"nullable\":true,\"metadata\":{}},{\"name\":\"order_time\",\"type\":\"timestamp\",\"nullable\":true,\"metadata\":{}}]}", "partitionColumns": [], "configuration": {}, "createdTime": int(time.time() * 1000)}}) + "\n")
        f.write(json.dumps(commit_data) + "\n")
        f.write(json.dumps(add_action) + "\n")
        
    print(f"Generated Delta log version 0 at {log_dir}")
    
    # Write version 1
    conn.execute(f"COPY mock_orders TO '{TABLE_PATH}/part-0001.parquet' (FORMAT PARQUET)")
    file_size2 = os.path.getsize(f"{TABLE_PATH}/part-0001.parquet")

    commit_data["commitInfo"]["operationParameters"]["mode"] = "Append"
    add_action["add"]["path"] = "part-0001.parquet"
    add_action["add"]["size"] = file_size2
    
    with open(os.path.join(log_dir, "00000000000000000001.json"), "w") as f:
        f.write(json.dumps(commit_data) + "\n")
        f.write(json.dumps(add_action) + "\n")

    print(f"Generated Delta log version 1 at {log_dir}")

    conn.close()
    
if __name__ == "__main__":
    import json
    generate_delta_data()
