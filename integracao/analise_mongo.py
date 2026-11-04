#!/usr/bin/env python3
import json
import os
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from operator import attrgetter
from typing import Callable, Iterable, Iterator, Optional, Sequence

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError
from pymongo.uri_parser import parse_uri

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
PRIMARY_ONLY = False
TOP: Optional[int] = 10
SLOW_THRESHOLD_SECS = 10.0
DEBUG = False

SERVER_SELECTION_TIMEOUT_MS = 10_000
OFFENDER_SHARE_THRESHOLD = 0.10
MAX_RELATED_SHOWN = 5
DIRECT_CONNECTION_EXCLUDED_OPTIONS = frozenset(
    {"replicaset", "directconnection", "loadbalanced", "srvservicename", "srvmaxhosts"}
)


@dataclass(frozen=True)
class Connection:
    node: str
    role: str
    opid: str
    client: str
    ip: str
    app_name: str
    user: str
    op: str
    ns: str
    active: bool
    secs: float
    plan_summary: str
    waiting_for_lock: bool

    @classmethod
    def from_current_op(cls, op: dict, node: str, role: str) -> "Connection":
        client = op.get("client") or op.get("client_s") or ""
        metadata = op.get("clientMetadata") or {}
        users = op.get("effectiveUsers") or op.get("authenticatedUsers") or []
        secs = op.get("secs_running")
        if secs is None and op.get("microsecs_running") is not None:
            secs = op["microsecs_running"] / 1_000_000

        return cls(
            node=node,
            role=role,
            opid=str(op.get("opid", "")),
            client=client,
            ip=client.rsplit(":", 1)[0],
            app_name=op.get("appName") or metadata.get("application", {}).get("name", ""),
            user=",".join(f"{u.get('user')}@{u.get('db')}" for u in users),
            op=op.get("op", ""),
            ns=op.get("ns", ""),
            active=bool(op.get("active")),
            secs=float(secs or 0),
            plan_summary=str(op.get("planSummary", "")),
            waiting_for_lock=bool(op.get("waitingForLock")),
        )

    @property
    def is_client(self) -> bool:
        return bool(self.client)

    @property
    def is_collscan(self) -> bool:
        return self.active and "COLLSCAN" in self.plan_summary

    @property
    def label(self) -> str:
        return self.app_name or self.ip


@dataclass
class NodeSnapshot:
    name: str
    role: str
    server_connections: dict
    raw_ops: list
    connections: list = field(init=False)

    def __post_init__(self) -> None:
        self.connections = [
            conn
            for conn in (Connection.from_current_op(op, self.name, self.role) for op in self.raw_ops)
            if conn.is_client
        ]


@dataclass
class GroupStats:
    total: int = 0
    active: int = 0
    max_secs: float = 0.0
    related: set = field(default_factory=set)

    @property
    def idle(self) -> int:
        return self.total - self.active

    def add(self, conn: Connection, related: str) -> None:
        self.total += 1
        if conn.active:
            self.active += 1
            self.max_secs = max(self.max_secs, conn.secs)
        if related:
            self.related.add(related)


@dataclass(frozen=True)
class Column:
    title: str
    width: int = 0
    align: str = "<"

    def render(self, value: object) -> str:
        text = str(value)
        return f"{text[:self.width]:{self.align}{self.width}}" if self.width else text


@dataclass(frozen=True)
class Ranking:
    title: str
    key: Callable[[Connection], str]
    related_title: str
    related: Callable[[Connection], str]
    active_only: bool = False


RANKINGS = (
    Ranking("POR APLICAÇÃO (appName)", attrgetter("app_name"), "IPs", attrgetter("ip")),
    Ranking("POR IP", attrgetter("ip"), "appNames", attrgetter("app_name")),
    Ranking("POR USUÁRIO", attrgetter("user"), "appNames", attrgetter("app_name")),
    Ranking("NAMESPACES COM OPERAÇÕES ATIVAS", attrgetter("ns"), "appNames", attrgetter("app_name"), True),
)

NODE_COLUMNS = (
    Column("nó", 45), Column("papel", 10), Column("current", 8, ">"), Column("available", 10, ">"),
    Column("active", 7, ">"), Column("totalCreated", 13, ">"), Column("currentOp", 10, ">"),
    Column("ativas", 7, ">"), Column("ociosas", 8, ">"),
)

RANKING_COLUMNS = (
    Column("chave", 45), Column("total", 6, ">"), Column("%", 6, ">"), Column("ativas", 7, ">"),
    Column("ociosas", 8, ">"), Column("maxSecs", 8, ">"),
)

SLOW_COLUMNS = (
    Column("secs", 7, ">"), Column("opid", 22), Column("nó", 30), Column("appName", 25),
    Column("ip", 16), Column("op", 8), Column("ns", 40), Column("plan", 40), Column("alertas"),
)



def discover_topology(client: MongoClient) -> tuple[str, list[str]]:
    hello = client.admin.command("hello")
    if hello.get("msg") == "isdbgrid":
        return "mongos", []
    if "setName" not in hello:
        return "standalone", []
    return "replicaset", [*hello.get("hosts", []), *hello.get("passives", [])]


@contextmanager
def direct_client(parsed_uri: dict, host: str) -> Iterator[MongoClient]:
    options = {
        key: value
        for key, value in parsed_uri["options"].items()
        if key.lower() not in DIRECT_CONNECTION_EXCLUDED_OPTIONS and not key.lower().endswith("ms")
    }
    if parsed_uri.get("username"):
        options.update(username=parsed_uri["username"], password=parsed_uri["password"])

    client = MongoClient(host, directConnection=True, serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS, **options)
    try:
        yield client
    finally:
        client.close()


def resolve_role(hello: dict) -> str:
    if hello.get("msg") == "isdbgrid":
        return "MONGOS"
    if hello.get("isWritablePrimary"):
        return "PRIMARY"
    if hello.get("secondary"):
        return "SECONDARY"
    return "OUTRO"


def snapshot_node(client: MongoClient, name: str) -> NodeSnapshot:
    admin = client.admin
    role = resolve_role(admin.command("hello"))

    try:
        server_connections = admin.command("serverStatus").get("connections", {})
    except OperationFailure as exc:
        print(f"  [{name}] serverStatus indisponível: {exc}")
        server_connections = {}

    raw_ops = admin.command({"currentOp": True, "$all": True})["inprog"]
    return NodeSnapshot(name=name, role=role, server_connections=server_connections, raw_ops=raw_ops)


def collect_snapshots(uri: str, primary_only: bool) -> list[NodeSnapshot]:
    with MongoClient(uri, serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS) as client:
        topology, hosts = discover_topology(client)
        print(f"Topologia: {topology}" + (f" | nós: {', '.join(hosts)}" if hosts else ""))

        if topology == "mongos":
            print("Aviso: via mongos o currentOp mostra só a visão do mongos; para ver por shard use a URI de cada shard.")

        if topology != "replicaset" or primary_only:
            print("Coletando nó principal...")
            return [snapshot_node(client, "principal")]

    parsed_uri = parse_uri(uri)
    snapshots = []
    for host in hosts:
        print(f"Coletando {host}...")
        try:
            with direct_client(parsed_uri, host) as client:
                snapshots.append(snapshot_node(client, host))
        except PyMongoError as exc:
            print(f"  [{host}] falha na coleta: {exc}")

    if snapshots:
        return snapshots

    print("Nenhum nó acessível por conexão direta; coletando apenas o nó principal...")
    with MongoClient(uri, serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS) as client:
        return [snapshot_node(client, "principal")]


def group_by(
    connections: Iterable[Connection],
    key: Callable[[Connection], str],
    related: Callable[[Connection], str],
) -> list[tuple[str, GroupStats]]:
    groups: dict[str, GroupStats] = defaultdict(GroupStats)
    for conn in connections:
        groups[key(conn) or "(vazio)"].add(conn, related(conn))
    return sorted(groups.items(), key=lambda item: item[1].total, reverse=True)


def join_limited(values: Iterable[str], limit: int = MAX_RELATED_SHOWN) -> str:
    ordered = sorted(values)
    suffix = " ..." if len(ordered) > limit else ""
    return ", ".join(ordered[:limit]) + suffix or "-"


def format_row(columns: Sequence[Column], values: Sequence[object]) -> str:
    return " ".join(column.render(value) for column, value in zip(columns, values))


def print_section(title: str) -> None:
    print(f"\n================ {title} ================\n")


def print_table(columns: Sequence[Column], rows: Iterable[Sequence[object]]) -> None:
    print(format_row(columns, [column.title for column in columns]))
    for row in rows:
        print(format_row(columns, row))


def print_node_summary(snapshots: Sequence[NodeSnapshot]) -> None:
    print_section("CONEXÕES POR NÓ (serverStatus x currentOp)")
    rows = []
    for snap in snapshots:
        status = snap.server_connections
        active = sum(conn.active for conn in snap.connections)
        rows.append((
            snap.name, snap.role, status.get("current", "-"), status.get("available", "-"),
            status.get("active", "-"), status.get("totalCreated", "-"),
            len(snap.connections), active, len(snap.connections) - active,
        ))
    print_table(NODE_COLUMNS, rows)

    connections = [conn for snap in snapshots for conn in snap.connections]
    internal = sum(len(snap.raw_ops) for snap in snapshots) - len(connections)
    active = sum(conn.active for conn in connections)
    print(
        f"\nConexões de clientes: {len(connections)} (ativas: {active}, ociosas: {len(connections) - active})"
        f" | threads internas ignoradas: {internal}"
    )


def print_ranking(ranking: Ranking, connections: Sequence[Connection], total: int, top: Optional[int]) -> None:
    print_section(ranking.title)
    scope = [conn for conn in connections if conn.active] if ranking.active_only else connections
    columns = (*RANKING_COLUMNS, Column(ranking.related_title))
    print_table(columns, (
        (name, stats.total, f"{stats.total / total:.1%}", stats.active, stats.idle,
         f"{stats.max_secs:.0f}", join_limited(stats.related))
        for name, stats in group_by(scope, ranking.key, ranking.related)[:top]
    ))


def alerts_for(conn: Connection) -> str:
    return " ".join(flag for flag, hit in (("COLLSCAN", conn.is_collscan), ("LOCK", conn.waiting_for_lock)) if hit)


def find_slow(connections: Iterable[Connection], threshold: float) -> list[Connection]:
    return sorted(
        (conn for conn in connections if conn.active and conn.secs >= threshold),
        key=attrgetter("secs"),
        reverse=True,
    )


def print_slow(slow: Sequence[Connection], threshold: float, top: Optional[int]) -> None:
    print_section(f"OPERAÇÕES ATIVAS >= {threshold:g}s ({len(slow)})")
    if not slow:
        print("Nenhuma.")
        return
    print_table(SLOW_COLUMNS, (
        (f"{conn.secs:.0f}", conn.opid, conn.node, conn.app_name, conn.ip, conn.op, conn.ns,
         conn.plan_summary, alerts_for(conn))
        for conn in slow[:top]
    ))


def find_offender_groups(connections: Sequence[Connection]) -> list[str]:
    total = len(connections)
    findings = []
    for label, key, related in (
        ("appName", attrgetter("app_name"), attrgetter("ip")),
        ("IP", attrgetter("ip"), attrgetter("app_name")),
    ):
        for name, stats in group_by(connections, key, related):
            share = stats.total / total
            if share < OFFENDER_SHARE_THRESHOLD:
                break
            findings.append(
                f"{label} {name}: {stats.total} conexões ({share:.1%}), {stats.idle} ociosas,"
                f" relacionados: {join_limited(stats.related)}"
            )
    return findings


def print_offenders(connections: Sequence[Connection], slow: Sequence[Connection], top: Optional[int]) -> None:
    print_section("RESUMO DE OFENSORES")
    if not connections:
        print("Nenhuma conexão de cliente encontrada.")
        return

    findings = find_offender_groups(connections)
    collscans = sum(conn.is_collscan for conn in connections)
    locks = sum(conn.waiting_for_lock for conn in connections)
    if collscans:
        findings.append(f"{collscans} operações ativas fazendo COLLSCAN (sem índice)")
    if locks:
        findings.append(f"{locks} operações aguardando lock")

    print("\n".join(f"- {finding}" for finding in findings) or "Nenhum ofensor evidente.")

    if slow:
        print("\nopids das operações lentas, apenas para referência. Este script NÃO encerra nada;")
        print("qualquer db.killOp(<opid>) deve ser avaliado e executado por pessoa autorizada.")
        for conn in slow[:top]:
            print(f"  {conn.opid}  ({conn.node}, {conn.secs:.0f}s, {conn.label}, {conn.ns})")


def print_debug(snapshots: Sequence[NodeSnapshot]) -> None:
    raw_ops = [op for snap in snapshots for op in snap.raw_ops]
    if not raw_ops:
        return
    print_section("CAMPOS DISPONÍVEIS")
    print("\n".join(sorted({key for op in raw_ops for key in op})))
    print_section("PRIMEIRA OPERAÇÃO")
    print(json.dumps(raw_ops[0], indent=4, default=str))


def main() -> None:
    if not MONGO_URI:
        raise SystemExit(f"Variável {MONGO_URI} não encontrada no ambiente/.env")
    print(f"Analisando {MONGO_URI} (somente leitura)")

    snapshots = collect_snapshots(MONGO_URI, PRIMARY_ONLY)
    if not snapshots:
        raise SystemExit("Nenhum nó pôde ser coletado.")

    if DEBUG:
        print_debug(snapshots)

    connections = [conn for snap in snapshots for conn in snap.connections]
    slow = find_slow(connections, SLOW_THRESHOLD_SECS)

    print_node_summary(snapshots)
    if connections:
        for ranking in RANKINGS:
            print_ranking(ranking, connections, len(connections), TOP)
    print_slow(slow, SLOW_THRESHOLD_SECS, TOP)
    print_offenders(connections, slow, TOP)


if __name__ == "__main__":
    main()
