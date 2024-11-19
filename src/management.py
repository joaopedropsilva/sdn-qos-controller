from mininet.clean import Cleanup
from typing import List
import yaml

from utils import File
from data import NetworkBuilder, Policy, PolicyTypes, Success, Error


class VirtualNetworkManager:
    def __init__(self):
        topo_schema_path = File.get_config()["topo_schema_path"]
        self.__builder = NetworkBuilder(topo_schema_path=topo_schema_path)
        self.__net = None

    def generate(self) -> Success | Error:
        (build_result, net) = self.__builder.build_network()

        if isinstance(build_result, Success):
            if net is not None:
                self.__net = net
                self.__net.start()

        return build_result

    def destroy(self) -> Success | Error:
        operation_result = Success.NetworkDestructionOk

        if self.__net is not None:
            try:
                self.__net.stop()
            except Exception:
                operation_result = Error.NetworkDestructionFailed

        Cleanup()

        return operation_result

    def report_state(self) -> None:
        pass

class FlowManager:
    __MIN_BANDWIDTH_RESERVED = 1
    __MAX_BANDWIDTH_RESERVED = 100

    def __init__(self):
        self.__config: dict = {}
        self.__policies: List[Policy] = []

    def __validate(self, policy: Policy) -> Success | Error:
        # Remover
        if policy.name == "":
            return Error.InvalidPolicyTrafficType
        
        if not isinstance(policy.traffic_type, PolicyTypes):
            return Error.InvalidPolicyTrafficType
        
        if not (policy.bandwidth < self.__MIN_BANDWIDTH_RESERVED
                and policy.bandwidth > self.__MAX_BANDWIDTH_RESERVED):
            return Error.InvalidPolicyBandwidth

        return Success.OperationOk

    def __init_framework_config(self) -> bool:
        # inicializa o arquivo de config do controlador
        return False

    def __update_tables(self, policy: Policy, operation: str) -> Success | Error:
        # altera o arquivo de config do controlador para lidar
        # com uma nova política ou com redirecionamento de tráfego

        if operation == "create":
            # Verifica se a política já existe, e caso exista, retorna aborta a operacao
            if any(p.traffic_type == policy.traffic_type for p in self.policies):
                return RoutineResults(
                    status=False,
                    err_reason=f"Política de tráfego {policy.traffic_type} já existe. Abortando a operação de criacao."
                )
            #A partir daqui admite-se que a politica ainda nao existe e que ela apresenta
            #todos os parametros necessarios para a criacao de uma nova regra.

            # cria a estrutura de regra com base na política
            rule = self.__create_rule(policy)

            # adiciona a nova política na lista de politicas
            self.policies.append(policy)

            # confirma que o tipo da politica nao existe no dicionario de configuracao
            # e cria uma entranda com uma lista vazia que depois recebe a regra,
            #  necessario antes de reescrever o arquivo acls.yaml do faucet
            if f"{policy.traffic_type}-traffic" not in self.__config:
                self.__config[f"{policy.traffic_type}-traffic"] = []

            self.__config[f"{policy.traffic_type}-traffic"].append(rule)

            # faz a escrita no arquivo acls.yaml e retorna a mensagem confirmando 
            self.__write_config()

            return RoutineResults(
                status=True,
                payload=f"Política de tráfego {policy.traffic_type} criada com sucesso."
            )

        elif operation == "update":
            for existing_policy in self.policies:
                if existing_policy.traffic_type == policy.traffic_type:
                    # Só modifica a banda se ela for diferente da atual
                    if existing_policy.bandwidth_reserved != policy.bandwidth_reserved:
                        existing_policy.bandwidth_reserved = policy.bandwidth_reserved
                        rule = self.__create_rule(policy)
                        # Atualiza a configuração
                        self.__config[f"{policy.traffic_type}-traffic"] = [rule]
                        self.__write_config()
                        return RoutineResults(
                            status=True,
                            payload=f"Política de tráfego {policy.traffic_type} atualizada com sucesso."
                        )
                    else:
                        # Se a banda não mudou, não faz nada
                        return RoutineResults(
                            status=True,
                            payload=f"Política de tráfego {policy.traffic_type} já está com a banda reservada correta."
                        )

            # caso a politica nao exista, retorna a negativa 
            return RoutineResults(
                status=False,
                err_reason=f"Política de tráfego {policy.traffic_type} não encontrada para atualização."
            )

        elif operation == "delete":
            # Verifica se a política existe na lista de políticas
            policy_exists = any(p.traffic_type == policy.traffic_type for p in self.policies)

            if not policy_exists:
                return RoutineResults(
                    status=False,
                    err_reason=f"Política de tráfego {policy.traffic_type} não encontrada para remoção."
                )

            # Remove a política da lista de políticas
            self.policies = [p for p in self.policies if p.traffic_type != policy.traffic_type]

            # Verifica e remove a política do dicionário de configuração, se existir
            if f"{policy.traffic_type}-traffic" in self.__config:
                del self.__config[f"{policy.traffic_type}-traffic"]

            # Atualiza o arquivo acls.yaml com a configuração modificada
            self.__write_config()

            return RoutineResults(
                status=True,
                payload=f"Política de tráfego {policy.traffic_type} removida com sucesso."
            )

        else:
            return RoutineResults(
                status=False,
                err_reason="Operação desconhecida. Use 'create', 'update' ou 'delete'."
            )
        

    def __create_rule(self, policy: Policy):
        """
        Cria a regra de tráfego baseada na política.
        """
        # Define a banda total disponível (exemplo: 1000 Mbps)
        total_bandwidth = 1000  # Exemplo de valor fixo. Isso pode vir de uma configuração ou ser dinâmico

        # Validação da banda reservada entre 1% e 100%
        if not (1 <= policy.bandwidth_reserved <= 100):
            return RoutineResults(
                status=False,
                err_reason="A banda reservada deve ser um valor entre 1 e 100."
            )

        # Calcula a banda reservada em Mbps e converte para bps
        reserved_bandwidth = (policy.bandwidth_reserved / 100) * total_bandwidth * 1000000

        # Criação de regra genérica com base no tipo de tráfego
        rule = {
            "acl_name": policy.name,  # Nome da política (como acl_name no formato do Faucet)
            "rules": [
                {
                    "dl_type": "0x800",  # Endereços IPv4 (exemplo genérico)
                    "nw_proto": 17 if policy.traffic_type == PolicyTypes.VOIP else 6,  # UDP (VoIP) ou TCP (HTTP e FTP)
                    "udp_dst": 53 if policy.traffic_type == PolicyTypes.VOIP else None,  # Porta padrão UDP para VoIP
                    "tcp_dst": 80 if policy.traffic_type != PolicyTypes.VOIP else None,  # Porta padrão para HTTP/FTP
                    "actions": {
                        "allow": 1,  # Permitir
                        "set_fields": [
                            {"bandwidth_reserved": reserved_bandwidth},  # Percentual tratado da banda reservada em bps
                        ]
                    }
                }
            ]
        }


        return rule


    def __write_config(self):
        
        """
        Atualiza o arquivo acls.yaml com o conteúdo de self.__config,
        mantendo as entradas já existentes.
        Retorna um objeto RoutineResults com o status da operação.
        """

        try:
            # Primeiro, carrega o conteúdo atual do arquivo acls.yaml
            try:
                with open("acls.yaml", "r") as file:
                    existing_config = yaml.safe_load(file) or {}
            except FileNotFoundError:
                # Se o arquivo não for encontrado, inicializa um dicionário vazio
                existing_config = {}

            # Atualiza o dicionário de configuração com as entradas existentes
            existing_config.update(self.__config)

            # Escreve o dicionário atualizado no arquivo acls.yaml
            with open("acls.yaml", "w") as file:
                yaml.dump(existing_config, file, default_flow_style=False)

            # Retorna um sucesso com a mensagem
            return RoutineResults(
                status=True,
                payload="Arquivo acls.yaml atualizado com sucesso!"
            )

        except Exception as e:
            # Retorna erro com a mensagem de exceção
            return RoutineResults(
                status=False,
                err_reason=f"Erro ao escrever no arquivo acls.yaml: {e}"
            )


    def __process_alerts(self) -> RoutineResults:
        # recebe o alerta do monitor
        # chama redirect_traffic se necessário
        return False

    def redirect_traffic(self) -> Success | Error:
        return Success.OperationOk

    def create(self, policy: Policy) -> Success | Error:
        validation_result = self.__validate(policy)
        if isinstance(validation_result, Error):
            return validation_result
        
        self.__policies.append(policy)

        tables_update_result = self.__update_tables()
        if isinstance(tables_update_result, Error):
            self.__policies.remove(policy)
            return tables_update_result
        
        return Success.PolicyCreationOk

    def update(self, policy: Policy) -> Success | Error:
        return Success.OperationOk

    def remove(self, policy: Policy) -> Success | Error:
        return Success.OperationOk

class Managers:
    def __init__(self):
        self.__virtual_network = VirtualNetworkManager()
        self.__flow = FlowManager()
        self.__is_network_alive = False

    @property
    def virtual_network(self) -> VirtualNetworkManager:
        return self.__virtual_network

    @property
    def flow(self) -> FlowManager:
        return self.__flow

    @property
    def is_network_alive(self) -> bool:
        return self.__is_network_alive

    @is_network_alive.setter
    def is_network_alive(self, network_status: bool) -> None:
        self.__is_network_alive = network_status

