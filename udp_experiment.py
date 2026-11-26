"""Optional comparison experiment: UDP loss & reordering on a 'typing indicator' style feed.
Simulates an unreliable network on loopback and shows why UDP needs app-level sequence numbers."""
import json, random, socket

random.seed(7)
rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); rx.bind(("127.0.0.1", 0))
tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
addr = rx.getsockname()

packets = [json.dumps({"seq": i, "text": f"typing update {i}"}).encode() for i in range(10)]
# Simulate network: drop ~30% and shuffle the rest (loopback itself rarely does this)
network = [p for p in packets if random.random() > 0.3]
random.shuffle(network)
for p in network:
    tx.sendto(p, addr)

rx.settimeout(0.5)
got, last = [], -1
try:
    while True:
        data, _ = rx.recvfrom(1024)
        m = json.loads(data)
        got.append(m["seq"])
        status = "OUT OF ORDER -> ignore (stale)" if m["seq"] < last else "ok"
        last = max(last, m["seq"])
        print(f"received seq={m['seq']}: {status}")
except socket.timeout:
    pass
print(f"\nSent 10, received {len(got)}; lost seq = {sorted(set(range(10)) - set(got))}")
print("UDP gave no retransmission: fine for ephemeral data, unacceptable for chat messages.")
