#!/usr/bin/env python3

import requests

import config

token = config.API_TOKEN

usernames = ['jupytertest', 'mshepard']

server = "http://uo-jupyterhub.westus2.cloudapp.azure.com"

for username in usernames:
    r = requests.post(f"{server}/users/{username}/server", headers={"Authorization": f"token {token}"})
    print(r.text)

