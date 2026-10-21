from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

host = "http://localhost:4443"
client = storage.Client(
    project="test",
    credentials=AnonymousCredentials(),
    client_options={"api_endpoint": host},
)
bucket = client.bucket("wenchang-dev")
if not bucket.exists():
    bucket = client.create_bucket("wenchang-dev")
