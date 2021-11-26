#!/bin/bash

docker build -t jupyterhub-datascience-singleuser \
  --build-arg BASE_IMAGE=jupyter/datascience-notebook \
  --build-arg JUPYTERHUB_VERSION=1.5.0 \
  .
docker tag docker.io/library/jupyterhub-datascience-singleuser uojupyterhub.azurecr.io/jupyterhub/datascience-singleuser
