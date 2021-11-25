#!/bin/bash

docker build -t jupyterhub-datascience-singleuser .
docker tag docker.io/library/jupyterhub-datascience-singleuser uojupyterhub.azurecr.io/jupyterhub/datascience-singleuser
