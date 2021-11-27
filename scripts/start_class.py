#!/usr/bin/env python3

import requests
import threading
import json

import config

token = config.API_TOKEN
HEADERS = {
    "Authorization": f"token {token}",
    "Content-Type": "application/json",
}
SERVER = "http://uo-jupyterhub.westus2.cloudapp.azure.com"

def task(username):
    requests.post(f"{SERVER}/hub/api/users/{username}/server", headers=HEADERS)
    print(f"{username}: spawning")

def precreate_user(username):
    print(f"{username} doesnt exist in jupyterhub, creating")
    requests.post(f"{SERVER}/hub/api/users/{username}", headers=HEADERS)

# This will eventually be replaced with some query for the users in the AD group
# but for right now we can just
usernames = ['jupytertest', 'mshepard']
usernames.extend([f"student{i}" for i in range(1,9)])


existing_users = [user["name"] for user in json.loads(requests.get(f"{SERVER}/hub/api/users", headers=HEADERS).text)]

threads = []
for username in usernames:
    if username not in existing_users:
        precreate_user(username)

    t = threading.Thread(target=task, args=(username,))
    threads.append(t)

for t in threads:
    t.start()

for t in threads:
    t.join()

