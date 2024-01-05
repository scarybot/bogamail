import boto3
from dataclasses import dataclass, field
from typing import Self
import json
import logging
import os
import time

queue_url_cache = {}
data_table_cache = None
logging.basicConfig(level=logging.INFO)


def data_table() -> str:
    global data_table_cache
    if data_table_cache is not None:
        return data_table_cache

    if os.environ.get("DATA_TABLE"):
        return os.environ.get("DATA_TABLE")
    else:
        ssm = boto3.client("ssm")
        parameter = ssm.get_parameter(Name=f"/bogamail/data_table")
        data_table_cache = parameter["Parameter"]["Value"]
        return data_table_cache


def store_scam_data(scammer_email_addr: str, data: dict) -> None:
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(data_table())
    table.put_item(Item={"email": scammer_email_addr, "data": json.dumps(data)})


def get_scam_data(email: str) -> dict:
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(data_table())
    response = table.get_item(Key={"email": email})
    if "Item" not in response:
        return {}
    else:
        return json.loads(response["Item"]["data"])
