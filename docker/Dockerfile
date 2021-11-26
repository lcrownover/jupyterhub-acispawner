FROM jupyter/datascience-notebook

RUN pip3 install --no-cache jupyterhub==1.5.0

RUN pip3 install --no-cache \
    datascience \
    otter-grader

RUN bash -c 'echo [[ -d ~/work ]] && cd ~/work >> /home/jovyan/.bashrc'
