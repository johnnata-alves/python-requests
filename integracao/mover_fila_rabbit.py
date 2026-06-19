

import argparse
import os
import ssl
import sys
from typing import Optional

import pika
from dotenv import load_dotenv
from pika.exceptions import AMQPError, UnroutableError

load_dotenv()

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "smart-yellow-zebra.rmq5.cloudamqp.com")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5671"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "events")
RABBITMQ_QUEUE = "service.document.document-typification.result-test"
RABBITMQ_QUEUE_SEND = "claim.regulation.claim-engine.document-typification.result.update"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move todas as mensagens de uma fila RabbitMQ para outra."
    )
    parser.add_argument("--host", default=RABBITMQ_HOST, help="Host do RabbitMQ")
    parser.add_argument("--port", type=int, default=RABBITMQ_PORT, help="Porta do RabbitMQ")
    parser.add_argument("--vhost", default=RABBITMQ_VHOST, help="Virtual host")
    parser.add_argument("--user", default=RABBITMQ_USER, help="Usuário")
    parser.add_argument("--password", default=RABBITMQ_PASSWORD, help="Senha")
    parser.add_argument("--source-queue", default=RABBITMQ_QUEUE, help="Fila de origem")
    parser.add_argument("--destination-queue", default=RABBITMQ_QUEUE_SEND, help="Fila de destino")
    parser.add_argument(
        "--declare-destination",
        action="store_true",
        help="Declara a fila de destino como durável antes de publicar",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Quantidade máxima de mensagens para mover (padrão: todas)",
    )
    parser.add_argument(
        "--prefetch",
        type=int,
        default=100,
        help="Prefetch do consumidor (padrão: 100)",
    )
    return parser.parse_args()

def build_connection(args: argparse.Namespace) -> pika.BlockingConnection:
    credentials = pika.PlainCredentials(args.user, args.password)
    ssl_options = None
    if args.port == 5671:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_default_certs()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        ssl_options = pika.SSLOptions(context, args.host)

    params = pika.ConnectionParameters(
        host=args.host,
        port=args.port,
        virtual_host=args.vhost,
        credentials=credentials,
        ssl_options=ssl_options,
        heartbeat=60,
        blocked_connection_timeout=300,
    )
    return pika.BlockingConnection(params)

def drain_queue(
    channel: pika.adapters.blocking_connection.BlockingChannel,
    source_queue: str,
    destination_queue: str,
    limit: Optional[int] = None,
) -> tuple[int, int]:
    moved = 0
    failed = 0

    while True:
        if limit is not None and moved >= limit:
            break

        method, properties, body = channel.basic_get(queue=source_queue, auto_ack=False)
        if method is None:
            break

        try:
            channel.basic_publish(
                exchange="",
                routing_key=destination_queue,
                body=body,
                properties=properties,
                mandatory=True,
            )
            channel.basic_ack(delivery_tag=method.delivery_tag)
            moved += 1
        except UnroutableError:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            failed += 1
            print(
                "Falha: mensagem não roteável para a fila de destino. Interrompendo.",
                file=sys.stderr,
            )
            break
        except AMQPError as exc:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            failed += 1
            print(f"Falha AMQP ao publicar: {exc}", file=sys.stderr)
            break

    return moved, failed

def main() -> int:
    args = parse_args()

    connection = None
    try:
        connection = build_connection(args)
        channel = connection.channel()

        channel.basic_qos(prefetch_count=args.prefetch)
        channel.confirm_delivery()

        if args.declare_destination:
            channel.queue_declare(queue=args.destination_queue, durable=True)

        moved, failed = drain_queue(
            channel=channel,
            source_queue=args.source_queue,
            destination_queue=args.destination_queue,
            limit=args.limit,
        )

        print(f"Mensagens movidas: {moved}")
        print(f"Falhas: {failed}")
        return 0 if failed == 0 else 1

    except AMQPError as exc:
        print(f"Erro de conexão/operação AMQP: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "Dica: valide host/porta/vhost/credenciais e se AMQPS (5671) está habilitado.",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print("Interrompido pelo usuário.", file=sys.stderr)
        return 130
    finally:
        if connection and connection.is_open:
            connection.close()

if __name__ == "__main__":
    raise SystemExit(main())
