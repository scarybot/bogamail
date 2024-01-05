import sys
import subprocess
import boto3
import yaml
import tempfile
import os
from lib.data import get_scam_data, store_scam_data

if len(sys.argv) != 2:
    print("Usage: python edit.py <scammer_email_address>")
    sys.exit(1)

email_address = sys.argv[1]

dynamodb = boto3.resource("dynamodb")

try:
    original_data = get_scam_data(email_address)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".yaml", mode='w+') as tf:
        yaml.dump(original_data, tf, allow_unicode=True)
        tf_path = tf.name

    editor = os.environ.get("EDITOR", "vi")
    subprocess.call([editor, tf_path])

    with open(tf_path, "r") as tf:
        modified_data = yaml.safe_load(tf)

    if modified_data != original_data:
        print("changes detected; updating the data item")
        store_scam_data(email_address, modified_data)
    else:
        print("no changes detected")

finally:
    if "tf_path" in locals():
        os.remove(tf_path)
