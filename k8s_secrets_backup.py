import os
import json
import hashlib
from kubernetes import client, config
import boto3
from botocore.exceptions import ClientError


def get_env_var(name, required=True, default=None):
    val = os.getenv(name, default)
    if required and val is None:
        raise ValueError(f"Missing required env var: {name}")
    return val


def sha256_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_k8s_client():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


def serialize_secret(secret):
    # Convert secret to JSON with data base64 encoded as string
    # We'll just store the raw .data dict (base64 values as strings)
    return json.dumps({
        "metadata": {
            "name": secret.metadata.name,
            "namespace": secret.metadata.namespace,
            "labels": secret.metadata.labels,
            "annotations": secret.metadata.annotations,
        },
        "type": secret.type,
        "data": secret.data or {}
    }, indent=2)


def deserialize_secret(json_bytes):
    obj = json.loads(json_bytes)
    return obj


class S3BackupRestore:
    def __init__(self):
        self.bucket = get_env_var("S3_BUCKET_NAME")
        self.backup_dir = get_env_var("S3_BACKUP_DIR", False, "k8s-secrets-backup")
        endpoint_url = os.getenv("S3_ENDPOINT_URL")
        access_key = get_env_var("S3_ACCESS_KEY_ID")
        secret_key = get_env_var("S3_SECRET_ACCESS_KEY")

        session = boto3.session.Session()
        self.s3 = session.client(
            service_name='s3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def s3_key(self, namespace, secret_name):
        # e.g. k8s-secrets-backup/default/my-secret.json
        return f"{self.backup_dir}/{namespace}/{secret_name}.json"

    def secret_exists(self, namespace, secret_name):
        key = self.s3_key(namespace, secret_name)
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == "404":
                return False
            else:
                raise

    def get_secret_backup(self, namespace, secret_name):
        key = self.s3_key(namespace, secret_name)
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=key)
            return obj['Body'].read()
        except ClientError as e:
            if e.response['Error']['Code'] == "NoSuchKey":
                return None
            raise

    def upload_secret(self, namespace, secret_name, content_bytes):
        key = self.s3_key(namespace, secret_name)
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=content_bytes)

    def list_backup_keys(self, namespace):
        prefix = f"{self.backup_dir}/{namespace}/"
        paginator = self.s3.get_paginator('list_objects_v2')
        keys = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                keys.append(obj['Key'])
        return keys


def backup_secrets(namespaces, k8s_client, s3_client):
    for ns in namespaces:
        print(f"Backing up secrets in namespace: {ns}")
        secrets = k8s_client.list_namespaced_secret(ns)
        for secret in secrets.items:
            # Skip service account tokens and default tokens
            if secret.type == "kubernetes.io/service-account-token":
                continue

            secret_json = serialize_secret(secret)
            secret_bytes = secret_json.encode("utf-8")
            secret_hash = sha256_hash(secret_bytes)

            existing_backup = s3_client.get_secret_backup(ns, secret.metadata.name)
            if existing_backup:
                existing_hash = sha256_hash(existing_backup)
                if existing_hash == secret_hash:
                    print(f"Skipping unchanged secret: {ns}/{secret.metadata.name}")
                    continue
                else:
                    print(f"Updating changed secret backup: {ns}/{secret.metadata.name}")
            else:
                print(f"Backing up new secret: {ns}/{secret.metadata.name}")

            s3_client.upload_secret(ns, secret.metadata.name, secret_bytes)


def restore_secrets(namespaces, k8s_client, s3_client, force_overwrite=False):
    for ns in namespaces:
        print(f"Restoring secrets in namespace: {ns}")
        keys = s3_client.list_backup_keys(ns)
        for key in keys:
            secret_name = key.split("/")[-1].replace(".json", "")
            secret_data_bytes = s3_client.get_secret_backup(ns, secret_name)
            if secret_data_bytes is None:
                print(f"Backup for secret {ns}/{secret_name} not found, skipping.")
                continue

            secret_data = deserialize_secret(secret_data_bytes)

            try:
                existing_secret = k8s_client.read_namespaced_secret(secret_name, ns)
                if not force_overwrite:
                    print(f"Secret {ns}/{secret_name} exists, skipping (force overwrite disabled).")
                    continue
                else:
                    print(f"Secret {ns}/{secret_name} exists, overwriting due to force overwrite.")
                    # Update secret
                    body = client.V1Secret(
                        metadata=client.V1ObjectMeta(
                            name=secret_name,
                            namespace=ns,
                            labels=secret_data.get("metadata", {}).get("labels"),
                            annotations=secret_data.get("metadata", {}).get("annotations"),
                        ),
                        data=secret_data.get("data", {}),
                        type=secret_data.get("type", "Opaque"),
                    )
                    k8s_client.replace_namespaced_secret(secret_name, ns, body)
            except client.exceptions.ApiException as e:
                if e.status == 404:
                    # Secret does not exist, create it
                    print(f"Creating secret {ns}/{secret_name}")
                    body = client.V1Secret(
                        metadata=client.V1ObjectMeta(
                            name=secret_name,
                            namespace=ns,
                            labels=secret_data.get("metadata", {}).get("labels"),
                            annotations=secret_data.get("metadata", {}).get("annotations"),
                        ),
                        data=secret_data.get("data", {}),
                        type=secret_data.get("type", "Opaque"),
                    )
                    k8s_client.create_namespaced_secret(ns, body)
                else:
                    raise


def main():
    namespaces_env = get_env_var("NAMESPACES")
    namespaces = [ns.strip() for ns in namespaces_env.split(",") if ns.strip()]

    restore_mode = os.getenv("RESTORE_MODE", "false").lower() == "true"
    force_overwrite = os.getenv("FORCE_OVERWRITE", "false").lower() == "true"

    k8s_client = get_k8s_client()
    s3_client = S3BackupRestore()

    if restore_mode:
        print("Starting restore mode...")
        restore_secrets(namespaces, k8s_client, s3_client, force_overwrite)
        print("Restore completed.")
    else:
        print("Starting backup mode...")
        backup_secrets(namespaces, k8s_client, s3_client)
        print("Backup completed.")


if __name__ == "__main__":
    main()
