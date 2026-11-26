"""Terminal TCP chat client.
Usage: python client.py [host] [port] [username]
Commands: /msg <user> <text> | /users | /quit | anything else = group message"""
import json, socket, sys, threading

host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
username = sys.argv[3] if len(sys.argv) > 3 else input("Username: ").strip()


def send(sock, obj):
    sock.sendall((json.dumps(obj) + "\n").encode())


def receiver(sock):
    for line in sock.makefile("r", encoding="utf-8"):      # reads until server closes
        try:
            m = json.loads(line)
        except ValueError:
            continue
        t = m.get("type")
        if t == "msg":
            print(f"\r[{m['from']}] {m['text']}")
        elif t == "private":
            print(f"\r[private {m['from']} -> {m['to']}] {m['text']}")
        elif t == "system":
            print(f"\r* {m['text']}")
        elif t == "users":
            print("\rOnline:", ", ".join(m["users"]))
        elif t == "joined":
            print(f"\rConnected as {m['username']}. Online: {', '.join(m['users'])}")
        elif t == "error":
            print(f"\r! {m['text']}")
    print("\rDisconnected from server.")
    sys.exit(0)


def main():
    sock = socket.create_connection((host, port), timeout=10)   # TCP 3-way handshake
    sock.settimeout(None)
    send(sock, {"type": "join", "username": username})
    threading.Thread(target=receiver, args=(sock,), daemon=True).start()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if line == "/quit":
                send(sock, {"type": "quit"})
                break
            elif line == "/users":
                send(sock, {"type": "users"})
            elif line.startswith("/msg "):
                parts = line.split(" ", 2)
                if len(parts) == 3:
                    send(sock, {"type": "private", "to": parts[1], "text": parts[2]})
                else:
                    print("Usage: /msg <user> <text>")
            else:
                send(sock, {"type": "msg", "text": line})
    except (KeyboardInterrupt, BrokenPipeError, ConnectionError):
        pass
    finally:
        sock.close()                                            # sends FIN


if __name__ == "__main__":
    main()
