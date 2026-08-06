#!/usr/bin/env python3
import json
import ssl
import sys
import urllib.request
import base64
from pathlib import Path
import kaggle

kaggle.api.authenticate()
u = kaggle.api.config_values.get("username", "")
k = kaggle.api.config_values.get("key", "")
auth = "Basic " + base64.b64encode(f"{u}:{k}".encode()).decode()

EP_ID = 90342558
url = "https://www.kaggle.com/api/i/competitions.EpisodeService/ShowEpisode"
req = urllib.request.Request(
    url,
    data=json.dumps({"id": EP_ID}).encode(),
    headers={"Content-Type": "application/json", "Authorization": auth},
)
ctx = ssl._create_unverified_context()
with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
    data = json.loads(resp.read().decode())

print(json.dumps(data, indent=2))
