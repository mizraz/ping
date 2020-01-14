import argparse
import time
import threading
import select
import socket
import sys
import logging

logging.basicConfig(stream=sys.stdout, level=logging.INFO)


def not_timeout(server_start_time):
    return time.time() - server_start_time < max_process_time


def get_host_name_first_10():
    host_name = socket.gethostname()
    if len(host_name) > 10:
        host_name = host_name[:10]
    return host_name


def print_summary(begin_process_time, host_name, amount_data):
    print('-' * 50 + "SUMMARY" + "-" * 50)
    print(f"client: received from host: {host_name}")
    print(f"total time: {time.time() - begin_process_time}")
    print(f"data recieved: {amount_data}")
    print('-' * 50 + "SUMMARY" + "-" * 50)


def tcp_request_worker(client):
    logging.info(f"Server: start handling tcp request of client")
    inputs = [client]
    begin_process_time = time.time()
    host_name = get_host_name_first_10()

    while inputs and not_timeout(begin_process_time):
        logging.debug('Server: waiting for the next event')
        readable, _, _ = select.select(inputs, [], [],
                                       buffer_ready_timeout)
        try:
            for s in readable:
                data, msg_size = decapsulate_msg_tcp_server(s)
                if data:
                    # A readable client socket has data
                    logging.debug(f'Server:  received {data} from {s.getpeername()}')

                    s.sendall(encapsulate_msg_tcp_server(host_name, msg_size))
                else:
                    inputs.remove(s)
                    s.close()
                    logging.info(f"Server: client socket closed")
        except Exception as e:
            logging.info(e)
            break
    logging.info("Server tcp: server is shuting down")


def decapsulate_msg_tcp_server(s):
    msg_size = int.from_bytes(s.recv(2), byteorder='big')
    data = s.recv(msg_size)
    return data, msg_size


def encapsulate_msg_tcp_server(host_name, msg_size):
    return (msg_size.to_bytes(2, byteorder='big') +
            len(host_name).to_bytes(2, byteorder='big') +
            f'{host_name}'.encode() +
            bytes(msg_size - len(host_name) - 2 - 2))


def start_tcp_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    logging.info(f'Server: starting up on {server_address[0]} port {server_address[1]}')
    server.bind(server_address)
    # Listen for incoming connections
    server.listen(5)
    # we got only 1 client
    # while True:
    client, addr = server.accept()
    t = threading.Thread(target=tcp_request_worker, args=(client,))
    t.start()


def start_udp_server():
    server_start_time = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    logging.info('Server starting up on {} port {}'.format(*server_address))
    sock.bind(server_address)
    inputs = [sock]
    host_name = get_host_name_first_10()

    while not_timeout(server_start_time):
        readable, _, _ = select.select(inputs, [], [],
                                       buffer_ready_timeout)
        logging.debug('\nServer: waiting to receive message')
        if readable:
            data, address = sock.recvfrom(4096)
            logging.debug(f'Server: received len(data) {len(data)} bytes from {address}')
            logging.debug(f'Server: data received: {data}')
            if data:
                sent = sock.sendto(encapsulate_msg_udp_server(data, host_name),
                                   address)
                logging.debug(f'Server: sent {sent} bytes back to {address}')
            else:
                logging.info("Server: socket is closing")
                sock.close()

    logging.info("Server is shuting down")
    sock.close()


def encapsulate_msg_udp_server(data, host_name):
    return (len(host_name).to_bytes(2, byteorder='big') +
            host_name.encode() +
            data[len(host_name) + 2:])


def start_tcp_client(msgs_bytes, msg_size):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(server_address)
    data_full = ''
    begin_process_time = time.time()
    try:
        # Send data
        for message in msgs_bytes:
            data = message
            logging.info('client: sending {!r}'.format(data))
            sock.sendall(data)

        # Look for the response
        amount_received = 0

        while amount_received < (msg_size)*number_of_pings and \
                not_timeout(begin_process_time):
            data, host_name_len, msg_size = decapsulate_msg_tcp_client(sock)
            data_full += data.decode()
            amount_received += len(data) + host_name_len
            logging.debug(f'client received {data} len: {len(data)}')

    finally:
        logging.info('client closing socket')
        sock.close()
        logging.info(f'client amount_received {amount_received}')
        host_name = data_full[:host_name_len]
        print(f'client: data_full: {data_full}')
        print(f"client: received from host: {host_name}")

    print_summary(begin_process_time, host_name, amount_received)


def decapsulate_msg_tcp_client(sock):
    ms_s = sock.recv(2)
    host_name_len = sock.recv(2)
    ms_s = int.from_bytes(ms_s, byteorder="big")
    host_name_len = int.from_bytes(host_name_len, byteorder="big")
    print(f'm_s {ms_s}')
    data = sock.recv(ms_s)
    return data, host_name_len, ms_s


def start_udp_client(msgs_bytes):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    amount_received = 0
    try:
        begin_process_time = time.time()
        # Send data
        for msg in msgs_bytes:
            logging.info(f'client sending {msg}')
            sent = sock.sendto(msg, server_address)
        inputs = [sock]
        while amount_received < len(msgs_bytes) and not_timeout(begin_process_time):
            logging.debug('client waiting for the next event udp')
            readable, _, _ = select.select(inputs, [], [],
                                           buffer_ready_timeout)
            # Handle inputs
            for s in readable:
                data, server = sock.recvfrom(4096)
                logging.debug(f'client  received {data}')
                amount_received += 1
                logging.info(f'client amount_recieved: {amount_received}')

    finally:
        logging.info('client closing socket')
        sock.close()
    logging.info(f'client: amount received {amount_received}')

    host_name = data[2:int(data[0:2].hex()) + 2].decode()
    print_summary(begin_process_time, host_name, amount_received)


def input_config(parser):
    parser.add_argument("-s", type=int,
                        help="size of buffer to send < 1024", default=900)
    parser.add_argument("-p", type=int,
                        help="port number",
                        default='9998')
    parser.add_argument("-d", type=str,
                        help="destination ipv4",
                        default='localhost')
    parser.add_argument("--protocol", type=str,
                        help="protocol: tcp / udp", )
    parser.add_argument("-t", type=int,
                        help="timeout", default=20)
    args = parser.parse_args()
    return args


def encapsulate_msg_client(msg_size, seq):
    return ((msg_size + len(f'Ping #{seq}.'))
            .to_bytes(2, byteorder='big') +
            f'Ping #{seq}.'.encode() +
            bytes(message_size))


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    args = input_config(parser)
    server_address = (args.d, args.p)
    protocol = args.protocol
    buffer_ready_timeout = 5
    max_process_time = args.t
    message_size = args.s
    number_of_pings = 4
    messages_bytes = []

    server_thread = None
    client_thread = None
    for i in range(number_of_pings):
        messages_bytes.append(encapsulate_msg_client(message_size, i))
    if protocol == "tcp":
        server_thread = threading.Thread(target=start_tcp_server)
        client_thread = threading.Thread(target=start_tcp_client, args=(messages_bytes, message_size))

    elif protocol == "udp":
        server_thread = threading.Thread(target=start_udp_server)
        client_thread = threading.Thread(target=start_udp_client, args=(messages_bytes,))
    else:
        print("error wrong input")
        exit()
    server_thread.start()
    client_thread.start()
    client_thread.join()
    server_thread.join()

    print("program ended")

