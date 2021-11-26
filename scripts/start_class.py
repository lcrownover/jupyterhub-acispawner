#!/usr/bin/env python3

import requests

import config

token = config.API_TOKEN
headers = {
    "Authorization": f"token {token}",
    "Content-Type": "application/json",
}
server = "http://uo-jupyterhub.westus2.cloudapp.azure.com"

usernames = ['jupytertest', 'mshepard']

for username in usernames:
    r = requests.post(f"{server}/hub/api/users/{username}/server", headers=headers)
    print(r.text)

