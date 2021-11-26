#!/usr/bin/env python3

import requests
import threading
import config

token = config.API_TOKEN
HEADERS = {
    "Authorization": f"token {token}",
    "Content-Type": "application/json",
}
SERVER = "http://uo-jupyterhub.westus2.cloudapp.azure.com"

def task(username):
    print(f"Starting: {username} ... ", end="", flush=True)
    requests.post(f"{SERVER}/hub/api/users/{username}/server", headers=HEADERS)
    print("done")

usernames = ['jupytertest', 'mshepard']

threads = []
for username in usernames:
    t = threading.Thread(target=task, args=username,)
    threads.append(t)

for t in threads:
    t.start()

for t in threads:
    t.join()

