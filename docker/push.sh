commit_hash="$(git log -1 --pretty=%h)"
docker push "uojupyterhub.azurecr.io/jupyterhub/datascience-singleuser:$commit_hash"
