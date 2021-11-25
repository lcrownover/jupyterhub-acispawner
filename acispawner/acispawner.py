import asyncio
import os

from azure.mgmt.containerinstance import ContainerInstanceManagementClient
from azure.mgmt.containerinstance.models import (
    Container,
    ContainerGroup,
    ContainerGroupNetworkProtocol,
    ContainerGroupSubnetId,
    ContainerPort,
    EnvironmentVariable,
    ImageRegistryCredential,
    IpAddress,
    OperatingSystemTypes,
    Port,
    ResourceRequests,
    ResourceRequirements,
)
from azure.identity import DefaultAzureCredential

from jupyterhub.spawner import Spawner
from traitlets import Bool, Dict, List, Unicode, Int


class ACISpawner(Spawner):
    image_registry_username = Unicode(
        None,
        allow_none=False,
        help="image registry username",
    ).tag(config=True)
    image_registry_password = Unicode(
        None,
        allow_none=False,
        help="image registry password",
    ).tag(config=True)
    image_registry_server = Unicode(
        None,
        allow_none=False,
        help="image registry server",
    ).tag(config=True)
    port = Int(
        80,
        allow_none=True,
        help="",
    ).tag(config=True)
    extra_paths = List(
        [],
        help="""
        Extra paths to prepend to the $PATH environment variable.

        {USERNAME} and {USERID} are expanded
        """,
    ).tag(config=True)

    spawn_timeout = 600
    container_cpu_limit = 1.0
    container_mem_limit = 4
    container_group_location = "West US 2"
    container_port = 80

    subscription_id = "377758e9-c4a1-44d2-b701-fc556632fd3c"
    resource_group = "jupyterhub-rg"
    vnet_name = "jupyterhub-rg-vnet"
    subnet_name = "ci"
    container_image = "uojupyterhub.azurecr.io/jupyterhub/datascience-singleuser"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aci_client = self.create_aci_client()
        self.acr_credentials = self.set_acr_credentials(
            server=self.image_registry_server,
            username=self.image_registry_username,
            password=self.image_registry_password,
        )

        # temporary
        import random
        import string

        self.rand = "".join(random.choices(string.ascii_lowercase, k=8))

    def _expand_user_vars(self, string):
        """
        Expand user related variables in a given string

        Currently expands:
          {USERNAME} -> Name of the user
          {USERID} -> UserID
        """
        return string.format(USERNAME=self.user.name, USERID=self.user.id)

    def create_aci_client(self):
        credential = DefaultAzureCredential()
        subscription_id = self.subscription_id
        return ContainerInstanceManagementClient(credential, subscription_id)

    def set_acr_credentials(self, server, username, password):
        return [
            ImageRegistryCredential(
                server=server,
                username=username,
                password=password,
            )
        ]

    def subnet_id(self):
        return (
            f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/Microsoft.Network/virtualNetworks/{self.vnet_name}/subnets/{self.subnet_name}",
        )

    @property
    def container_group_name(self):
        # this is temporary so i can create a bunch
        return f"z-jupyter-ci-{self.rand}"
        # return f"jupyter-ci-{self.user.name}"

    @property
    def container_name(self):
        return f"jupyter-{self.user.name}"

    async def spawn_container_group(self, cmd, env):
        container_resource_requests = ResourceRequests(
            memory_in_gb=self.container_mem_limit,
            cpu=self.container_cpu_limit,
        )
        container_resource_requirements = ResourceRequirements(
            requests=container_resource_requests
        )
        environment_variables = [
            EnvironmentVariable(name=k, value=v) for k, v in env.items()
        ]
        container = Container(
            name=self.container_name,
            image=self.container_image,
            resources=container_resource_requirements,
            ports=[ContainerPort(port=self.container_port)],
            command=cmd,
            environment_variables=environment_variables,
        )

        # configure the container group
        subnet_ids = [
            ContainerGroupSubnetId(
                id=self.subnet_id(),
                name=self.subnet_name,
            )
        ]
        ports = [
            Port(protocol=ContainerGroupNetworkProtocol.tcp, port=self.container_port)
        ]
        group_ip_address = IpAddress(ports=ports, type="Private")

        group = ContainerGroup(
            location=self.container_group_location,
            containers=[container],
            os_type=OperatingSystemTypes.linux,
            ip_address=group_ip_address,
            image_registry_credentials=self.acr_credentials,
            subnet_ids=subnet_ids,
        )

        self.aci_client.container_groups.begin_create_or_update(
            self.resource_group, self.container_group_name, group
        )

        return None

    async def start(self):
        # get environment variables,
        # several of which are required for configuring the single-user server
        env = self.get_env()
        cmd = []
        # get jupyterhub command to run,
        # typically ['jupyterhub-singleuser']
        cmd.extend(self.cmd)
        cmd.extend(self.get_args())

        if self.extra_paths:
            env["PATH"] = "{extrapath}:{curpath}".format(
                curpath=env["PATH"],
                extrapath=":".join(
                    [self._expand_user_vars(p) for p in self.extra_paths]
                ),
            )

        self.log.info("cmd: %s, env: %s", cmd, env)

        await self.spawn_container_group(cmd, env)

        for _ in range(self.spawn_timeout):
            is_up = await self.poll()
            if is_up is None:
                container_group = self.aci_client.container_groups.get(
                    self.resource_group, self.container_group_name
                )
                net = container_group.ip_address
                self.log.info(net)
                ip = net.ip
                port = net.ports[0].port
                return (ip, port)
            await asyncio.sleep(1)

        return None

    async def poll(self):
        """
        Return None if running
        Otherwise integer exit status
        """
        container_group = self.aci_client.container_groups.get(
            self.resource_group, self.container_group_name
        )
        state = container_group.provisioning_state
        self.log.info(f"{state}: {self.container_group_name}")
        if state == "Succeeded":
            self.log.info(type(container_group))
            self.log.info(container_group)
            self.log.info(f"{state}: {self.container_group_name}")
            return None
        return 0

    async def stop(self):
        # group = self.aci_client.container_groups.get(
        #     "jupyterhub-rg", self.container_group_name
        # )
        # self.aci_client.container_groups.begin_delete(
        #     "jupyterhub-rg", self.container_group_name, group
        # )
        yield None

    def get_state(self):
        """get the current state"""
        state = super().get_state()
        if self.pid:
            state["pid"] = self.pid
        return state

    def load_state(self, state):
        """load state from the database"""
        super().load_state(state)
        if "pid" in state:
            self.pid = state["pid"]

    def clear_state(self):
        """clear any state (called after shutdown)"""
        super().clear_state()
        self.pid = 0
