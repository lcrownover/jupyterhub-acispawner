import asyncio
import socket

from azure.mgmt.containerinstance import ContainerInstanceManagementClient
from azure.mgmt.containerinstance.models import (
    AzureFileVolume,
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
    Volume,
    VolumeMount,
)
from azure.identity import DefaultAzureCredential
from azure.storage.fileshare import ShareServiceClient

from jupyterhub.spawner import Spawner
from traitlets import List, Unicode, Int, Float, Bool


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
    storage_account_name = Unicode(
        None,
        allow_none=False,
        help="storage account name for mounted storage",
    ).tag(config=True)
    storage_account_key = Unicode(
        None,
        allow_none=False,
        help="storage account key for mounted storage",
    ).tag(config=True)
    storage_quota = Int(
        2,
        allow_none=True,
        help="storage quota in GB for each user share",
    ).tag(config=True)
    storage_access_tier = Unicode(
        "Hot",
        allow_none=True,
        help="storage access tier for each user share",
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
        600,
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
    allow_insecure_writes = Bool(
        True,
        allow_none=True,
        help="azure files mount with 777 permissions, jupyter needs to be okay with this",
    ).tag(config=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aci_client = self.create_aci_client()
        self.storage_client = self.create_storage_client()
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

    def create_storage_client(self):
        account_url = f"https://{self.storage_account_name}.file.core.windows.net/"
        return ShareServiceClient(
            account_url=account_url, credential=self.storage_account_key
        )

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

    def get_container_group(self):
        try:
            return self.aci_client.container_groups.get(
                self.resource_group, self.container_group_name
            )
        except Exception as e:
            self.log.debug(f"error getting container: {e}")
            return None

    async def create_container_group(self, group):
        for _ in range(3):
            try:
                self.aci_client.container_groups.begin_create_or_update(
                    self.resource_group, self.container_group_name, group
                )
                return None
            except Exception as e:
                if "is still transitioning, please retry later" in str(e):
                    self.log.info(
                        f"container is still transitioning, waiting 10s then trying again"
                    )
                    await asyncio.sleep(10)

    def delete_container_group(self):
        try:
            self.aci_client.container_groups.begin_delete(
                self.resource_group, self.container_group_name
            )
        except:
            print(f"container group {self.container_group_name} doesnt exist")

    def start_container_group(self):
        self.aci_client.container_groups.begin_start(
            self.resource_group, self.container_group_name
        )

    def stop_container_group(self):
        self.aci_client.container_groups.stop(
            self.resource_group, self.container_group_name
        )

    def container_volume_mounts(self):
        return [
            VolumeMount(
                name=self.share_name,
                mount_path="/home/jovyan/work",
            )
        ]

    def group_volumes(self):
        v = Volume(
            name=self.share_name,
            azure_file=AzureFileVolume(
                share_name=self.share_name,
                storage_account_name=self.storage_account_name,
                storage_account_key=self.storage_account_key,
            ),
        )
        return [v]

    @property
    def share_name(self):
        return f"vol-{self.user.name}"

    async def create_share(self):
        try:
            self.storage_client.create_share(
                share_name=self.share_name,
                quota=self.storage_quota,
                access_tier=self.storage_access_tier,
            )
        except Exception as e:
            self.log.info(e)
            self.log.info(
                f"tried to create share: {self.share_name} but it already exists"
            )

    async def share_exists(self):
        shares = list(self.storage_client.list_shares())
        for share in shares:
            if share.name == self.share_name:
                return True
        return False

    async def create_share_if_not_exist(self):
        if not await self.share_exists():
            self.log.info(f"creating new share for: {self.user.name}")
            await self.create_share()
            return None

    def build_container_request(self, cmd, env):
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
            volume_mounts=self.container_volume_mounts(),
        )
        return container

    def build_container_group_request(self, container):
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
        volumes = self.group_volumes()
        group_ip_address = IpAddress(ports=ports, type="Private")

        group = ContainerGroup(
            location=self.container_group_location,
            containers=[container],
            os_type=OperatingSystemTypes.linux,
            ip_address=group_ip_address,
            image_registry_credentials=self.acr_credentials,
            subnet_ids=subnet_ids,
            volumes=volumes,
        )
        return group

    def get_api_token(self, container_group):
        container = container_group.containers[0]
        try:
            for ev in container.environmentVariables:
                if ev["name"].startswith(("JPY_API_TOKEN=", "JUPYTERHUB_API_TOKEN=")):
                    return ev["value"]
        except:
            return None

    def get_ip_port(self, container_group):
        net = container_group.ip_address
        ip = net.ip
        port = net.ports[0].port
        return ip, port

    def test_connect(self, container_group):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ip, port = self.get_ip_port(container_group)
        res = sock.connect_ex((ip, port))
        sock.close()
        if res == 0:
            return True
        return False

    def is_ready(self, container_group):
        """Returns True only if all readychecks pass"""
        if not container_group:
            return False
        if not container_group.provisioning_state == "Succeeded":
            return False
        if not container_group.instance_view.state == "Running":
            return False
        if not self.test_connect(container_group):
            return False
        return True

    async def start_existing(self):
        """Returns True if an existing container group succeeds a start call"""
        if not self.get_container_group():
            return False
        try:
            self.start_container_group()
            return True
        except Exception as e:
            self.log.info(e)
            self.log.info(
                f"existing container group failed to start: {self.container_group_name}"
            )
            return False

    async def spawn_container_group(self, cmd, env, recreate=False):
        """
        Returns None when the container group is created

        Use recreate to delete the existing container group before creating
        """
        if recreate:
            self.delete_container_group()
        self.log.info(f"creating: {self.container_group_name}")
        container = self.build_container_request(cmd, env)
        group = self.build_container_group_request(container)
        await self.create_container_group(group)
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

        if self.allow_insecure_writes:
            env["JUPYTER_ALLOW_INSECURE_WRITES"] = "true"

        # self.log.info(f"cmd: {cmd}, env: {env}")

        # containers should shut down when not in use, but not delete themselves.
        # if the container exists, we just want to return the necessary bits
        # returns None,None if anything is wrong
        exists = await self.start_existing()
        if not exists:
            # otherwise create the share if it doesnt exist
            await self.create_share_if_not_exist()
            # then spawn it
            await self.spawn_container_group(cmd, env, recreate=False)

        # Poll every 10 seconds, calculate timeout based on that.
        poll_sleep = 10
        poll_timeout = int(self.spawn_timeout / poll_sleep)

        for s in range(poll_timeout):
            self.log.info(f"poll: {self.user.name}: {s*poll_sleep}s")
            is_up = await self.poll()
            if is_up is None:  # None == it's done
                self.log.info(f"ready {self.user.name}: {s*poll_sleep}s")
                ip, port = self.get_ip_port(self.get_container_group())
                return (ip, port)
            await asyncio.sleep(poll_sleep)
        return None

    async def poll(self):
        """
        Return None if running
        Otherwise integer exit status
        """
        container_group = self.get_container_group()
        if self.is_ready(container_group):
            return None
        return 0

    async def stop(self):
        try:
            self.stop_container_group()
        except Exception as e:
            self.log.error(f"error stopping container group: {e}")
        return None

    # we don't need any state, these are unused
    def get_state(self):
        """get the current state"""
        state = super().get_state()
        return state

    def load_state(self, state):
        """load state from the database"""
        super().load_state(state)

    def clear_state(self):
        """clear any state (called after shutdown)"""
        super().clear_state()
