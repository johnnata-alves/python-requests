#!/usr/bin/env python3
import os

from pymongo import MongoClient
from collections import Counter
import csv
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()



# =====================================================
# CONFIGURAÇÃO
# =====================================================

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")

# =====================================================
# CONEXÃO
# =====================================================

client = MongoClient(MONGO_URI)
admin = client.admin

print("Obtendo currentOp...")

result = admin.command({
    "currentOp": True,
    "$all": True
})

ops = result["inprog"]

print(f"\nTotal de operações encontradas: {len(ops)}")

# =====================================================
# MOSTRAR TODOS OS CAMPOS DISPONÍVEIS
# =====================================================

if ops:
    print("\n================ CAMPOS DISPONÍVEIS ================\n")

    for field in sorted(ops[0].keys()):
        print(field)

# =====================================================
# CONTADORES
# =====================================================

connections_by_ip = Counter()
connections_by_driver = Counter()
connections_by_operation = Counter()
connections_by_namespace = Counter()
connections_by_user = Counter()
connections_by_effective_user = Counter()

# =====================================================
# CSV
# =====================================================

csv_name = f"mongo_connections_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

with open(csv_name, "w", newline="", encoding="utf-8") as f:

    writer = csv.writer(f)

    writer.writerow([
        "connectionId",
        "client",
        "ip",
        "driver",
        "driverVersion",
        "platform",
        "operation",
        "namespace",
        "active",
        "secondsRunning",
        "authenticatedUsers",
        "effectiveUsers"
    ])

    for op in ops:

        client_addr = op.get("client", "")

        ip = ""
        if client_addr:
            ip = client_addr.split(":")[0]

        meta = op.get("clientMetadata", {})

        driver = meta.get("driver", {}).get("name", "")
        driver_version = meta.get("driver", {}).get("version", "")

        platform = meta.get("platform", "")

        operation = op.get("op", "")
        namespace = op.get("ns", "")

        active = op.get("active")

        secs = op.get("secs_running", "")

        authenticated = op.get("authenticatedUsers")
        effective = op.get("effectiveUsers")

        if ip:
            connections_by_ip[ip] += 1

        if driver:
            connections_by_driver[f"{driver} {driver_version}"] += 1

        if operation:
            connections_by_operation[operation] += 1

        if namespace:
            connections_by_namespace[namespace] += 1

        if authenticated:
            for u in authenticated:
                key = f"{u.get('user')}@{u.get('db')}"
                connections_by_user[key] += 1

        if effective:
            for u in effective:
                key = f"{u.get('user')}@{u.get('db')}"
                connections_by_effective_user[key] += 1

        writer.writerow([
            op.get("connectionId"),
            client_addr,
            ip,
            driver,
            driver_version,
            platform,
            operation,
            namespace,
            active,
            secs,
            json.dumps(authenticated),
            json.dumps(effective)
        ])

# =====================================================
# RELATÓRIO
# =====================================================

print("\n================ CONEXÕES POR IP ================\n")

for ip, total in connections_by_ip.most_common():
    print(f"{ip:20} {total}")

print("\n================ DRIVERS ================\n")

for drv, total in connections_by_driver.most_common():
    print(f"{drv:40} {total}")

print("\n================ OPERAÇÕES ================\n")

for op, total in connections_by_operation.most_common():
    print(f"{op:20} {total}")

print("\n================ NAMESPACES ================\n")

for ns, total in connections_by_namespace.most_common():
    print(f"{ns:40} {total}")

print("\n================ USUÁRIOS (authenticatedUsers) ================\n")

if connections_by_user:
    for user, total in connections_by_user.most_common():
        print(f"{user:<50} {total}")
else:
    print("O servidor não retornou authenticatedUsers.")

print("\n================ USUÁRIOS (effectiveUsers) ================\n")

if connections_by_effective_user:
    for user, total in connections_by_effective_user.most_common():
        print(f"{user:<50} {total}")
else:
    print("O servidor não retornou effectiveUsers.")

print("\nCSV gerado:", csv_name)

# =====================================================
# EXEMPLO COMPLETO DA PRIMEIRA OPERAÇÃO
# =====================================================

if ops:
    print("\n================ PRIMEIRA OPERAÇÃO ================\n")
    print(json.dumps(ops[0], indent=4, default=str))
