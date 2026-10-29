import argparse
import json
import socket

# default port
TCP_PORT = 9000
HOST_IP = "127.0.0.1"

def parse_args():
    parser = argparse.ArgumentParser()
    # --host
    parser.add_argument("--host", default=HOST_IP, help="Server host to connect to")
    parser.add_argument(
        "--port", default=TCP_PORT, type=int, help="Specify the tcp port"
    )
    args = parser.parse_args()

    return args


def print_response(line):
    try:
        obj = json.loads(line)
        print(json.dumps(obj, indent=2))
    except json.JSONDecodeError:
        print(line)


def send_command(sock, reader, command):
    sock.sendall((command + "\n").encode("utf-8"))
    response = reader.readline()
    if response == "":
        raise ConnectionError("Server closed the connection")
    return response

def main():
    args = parse_args()

    try:
        sock = socket.create_connection((args.host, args.port))
    except ConnectionRefusedError:
        print(f"Could not connect to {args.host}:{args.port}. Is the server running?")
        return

    reader = sock.makefile("r", encoding="utf-8")

    print(f"Connected to {args.host}:{args.port}. Ctrl+D quits cleanly. Ctrl+C disconnects abruptly.")

    try:
        while True:
            try: 
                command = input("> ")
                command = command.strip()
                if command == "":
                    continue
                response = send_command(sock, reader, command)
                print_response(response)
                if command.upper() == "QUIT":
                    break
            except EOFError:
                print()
                response = send_command(sock, reader, "QUIT")
                print_response(response)
                break
    except KeyboardInterrupt:
        print("Disconnected without QUIT.")

    except ConnectionError as e:
        print(f"Connection to server lost: {e}")

    finally:
        reader.close()
        sock.close()

if __name__ == "__main__":
    main()
