#!/bin/bash

commit_hash="$(git log -1 --pretty=%h)"
docker build -t "jupyterhub-datascience-singleuser:$commit_hash" \
  --build-arg BASE_IMAGE=jupyter/datascience-notebook \
  --build-arg JUPYTERHUB_VERSION=1.5.0 \
  .
docker tag \
    "docker.io/library/jupyterhub-datascience-singleuser:$commit_hash" \
    "uojupyterhub.azurecr.io/jupyterhub/datascience-singleuser:$commit_hash"
