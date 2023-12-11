import boto3

# Substitua 'FortiWeb-IPv4' pelo nome do seu IP set
ip_set_name = 'FortiWeb-IPv4'
ip_set_scope = 'REGIONAL'

# Substitua 'ips.txt' pelo caminho e nome do seu arquivo de IPs
nome_arquivo = 'allowed_ips4.txt'

# Lê os IPs do arquivo
with open(nome_arquivo, 'r') as arquivo:
    ips = arquivo.read().splitlines()

# Cria uma instância do cliente WAFv2
wafv2_client = boto3.client('wafv2')

# Lista todos os IP sets
try:
    response = wafv2_client.list_ip_sets(Scope=ip_set_scope)
    ip_sets = response['IPSets']

    # Verifica se o IP set já existe
    ip_set_id = None
    for ip_set in ip_sets:
        if ip_set['Name'] == ip_set_name:
            print(f"IP set '{ip_set_name}' encontrado.")
            ip_set_id = ip_set['Id']
            break

    # Se o IP set já existe, atualiza-o
    if ip_set_id:
        response = wafv2_client.update_ip_set(
            Name=ip_set_name,
            Scope=ip_set_scope,
            Id=ip_set_id,
            Addresses=ips,
            LockToken=wafv2_client.get_ip_set(Id=ip_set_id, Name=ip_set_name, Scope=ip_set_scope)['LockToken']
        )
        print(f"IP set '{ip_set_name}' atualizado com sucesso.")

    # Se o IP set não existe, cria-o
    else:
        response = wafv2_client.create_ip_set(
            Name=ip_set_name,
            Scope=ip_set_scope,
            IPAddressVersion='IPV4',
            Addresses=ips
        )
        print(f"IP set '{ip_set_name}' criado com sucesso.")

except Exception as e:
    print(f"Ocorreu um erro: {e}")
