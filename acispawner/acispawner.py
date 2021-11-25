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
from traitlets import List, Unicode, Int, Float


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
    container_image = Unicode(
        None,
        allow_none=False,
        help="url of container image",
    ).tag(config=True)
    subscription_id = Unicode(
        None,
        allow_none=False,
        help="azure subscription id",
    ).tag(config=True)
    resource_group = Unicode(
        None,
        allow_none=False,
        help="azure resource group",
    ).tag(config=True)
    container_group_location = Unicode(
        None,
        allow_none=False,
        help="location for the container group",
    ).tag(config=True)
    vnet_name = Unicode(
        None,
        allow_none=False,
        help="azure virtual network name to deploy containers on",
    ).tag(config=True)
    subnet_name = Unicode(
        None,
        allow_none=False,
        help="azure virtual network subnet name to deploy containers on",
    ).tag(config=True)
    port = Int(
        80,
        allow_none=True,
        help="port for the container to listen on",
    ).tag(config=True)
    container_cpu_limit = Float(
        1.0,
        allow_none=True,
        help="how many CPUs to allocate to each container",
    ).tag(config=True)
    container_mem_limit = Int(
        4,
        allow_none=True,
        help="how much memory to allocate to each container",
    ).tag(config=True)
    spawn_timeout = Int(
        300,
        allow_none=True,
        help="timeout until spawn fails. azure spawning is slow, expect several minutes",
    ).tag(config=True)
    extra_paths = List(
        [],
        help="""
        Extra paths to prepend to the $PATH environment variable.

        {USERNAME} and {USERID} are expanded
        """,
    ).tag(config=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aci_client = self.create_aci_client()
        self.acr_credentials = self.set_acr_credentials(
            server=self.image_registry_server,
            username=self.image_registry_username,
            password=self.image_registry_password,
        )
        self.container_port = self.port

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
        return f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/Microsoft.Network/virtualNetworks/{self.vnet_name}/subnets/{self.subnet_name}"

    @property
    def container_group_name(self):
        return f"z-jupyter-ci-{self.user.name}"

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
        env = self.get_env()
        cmd = []
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
                ip = container_group.ip_address.ip
                port = container_group.ip_address.ports[0].port
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
        state = container_group.instance_view.state
        self.log.info(f"{state}: {self.container_group_name}")
        if state == "Running":
            return None
        return 0

    async def stop(self):
        try:
            group = self.aci_client.container_groups.get(
                self.resource_group, self.container_group_name
            )
            self.log.info(f"deleting container group: {group}")
            self.aci_client.container_groups.begin_delete(
                self.resource_group, self.container_group_name
            )
        except Exception as e:
            self.log.info(f"error deleting container group: {e}")
        yield None

    def get_state(self):
        """get the current state"""
        state = super().get_state()
        # if self.container_group_name:
        #     state["container_group_name"] = self.container_group_name
        return state

    def load_state(self, state):
        """load state from the database"""
        super().load_state(state)
        # if "container_group_name" in state:
        #     self.container_group_name = state["container_group_name"]

    def clear_state(self):
        """clear any state (called after shutdown)"""
        super().clear_state()
        # self.container_group_name = ""
