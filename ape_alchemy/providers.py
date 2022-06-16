import os
from typing import Dict, Tuple

from ape.api import UpstreamProvider, Web3Provider
from ape.exceptions import ContractLogicError, ProviderError, VirtualMachineError
from web3 import HTTPProvider, Web3  # type: ignore
from web3.exceptions import ContractLogicError as Web3ContractLogicError
from web3.gas_strategies.rpc import rpc_gas_price_strategy
from web3.middleware import geth_poa_middleware


_ETH_ENVIRONMENT_VARIABLE_NAMES = ("WEB3_ALCHEMY_PROJECT_ID", "WEB3_ALCHEMY_API_KEY")
_ARB_ENVIRONMENT_VARIABLE_NAMES = ("WEB3_ARBITRUM_ALCHEMY_PROJECT_ID", "WEB3_ARBITRUM_ALCHEMY_API_KEY")


class AlchemyProviderError(ProviderError):
    """
    An error raised by the Alchemy provider plugin.
    """


class MissingProjectKeyError(AlchemyProviderError):
    def __init__(self, options: Tuple[str]):
        env_var_str = ", ".join([f"${n}" for n in options])
        super().__init__(f"Must set one of {env_var_str}.")


class AlchemyEthereumProvider(Web3Provider, UpstreamProvider):
    """
    A web3 provider using an HTTP connection to Alchemy.

    Docs: https://docs.alchemy.com/alchemy/
    """

    network_uris: Dict[tuple, str] = {}

    @property
    def uri(self):
        ecosystem_name = self.network.ecosystem.name
        network_name = self.network.name
        if (ecosystem_name, network_name) in self.network_uris:
            return self.network_uris[(ecosystem_name, network_name)]

        key = None

        options_by_ecosystem = {"ethereum": _ETH_ENVIRONMENT_VARIABLE_NAMES, "arbitrum": _ARB_ENVIRONMENT_VARIABLE_NAMES}
        options = options_by_ecosystem[ecosystem_name]
        for env_var_name in options:
            env_var = os.environ.get(env_var_name)
            if env_var:
                key = env_var
                break

        if not key:
            raise MissingProjectKeyError(options)

        network_formats_by_ecosystem = {
            "etheruem": f"https://eth-{0}.alchemyapi.io/v2/{1}",
            "arbitrum": f"https://arb-{0}.g.alchemyapi.io/v2/{1}"
        }

        network_format = network_formats_by_ecosystem[ecosystem_name]
        uri = network = network_format.format(self.network.name, key)
        self.network_uris[(ecosystem_name, network_name)] = network_uri
        return network_uri

    @property
    def connection_str(self) -> str:
        return self.uri

    def connect(self):
        self._web3 = Web3(HTTPProvider(self.uri))
        if self._web3.eth.chain_id in (4, 5, 42):
            self._web3.middleware_onion.inject(geth_poa_middleware, layer=0)
        self._web3.eth.set_gas_price_strategy(rpc_gas_price_strategy)

    def disconnect(self):
        self._web3 = None  # type: ignore

    def get_virtual_machine_error(self, exception: Exception) -> VirtualMachineError:
        if not hasattr(exception, "args") or not len(exception.args):
            return VirtualMachineError(base_err=exception)

        args = exception.args
        message = args[0]
        if (
            not isinstance(exception, Web3ContractLogicError)
            and isinstance(message, dict)
            and "message" in message
        ):
            # Is some other VM error, like gas related
            return VirtualMachineError(message=message["message"])

        elif not isinstance(message, str):
            return VirtualMachineError(base_err=exception)

        # If get here, we have detected a contract logic related revert.
        message_prefix = "execution reverted"
        if message.startswith(message_prefix):
            message = message.replace(message_prefix, "")

            if ":" in message:
                # Was given a revert message
                message = message.split(":")[-1].strip()
                return ContractLogicError(revert_message=message)
            else:
                # No revert message
                return ContractLogicError()

        return VirtualMachineError(message=message)
