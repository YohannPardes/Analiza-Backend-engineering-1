"""Developer helper: start the containers, run checks, look at logs.

    python demo.py              start everything, run all checks, show events and logs
    python demo.py --help       list the commands
"""
import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
A, B = "http://localhost:8081", "http://localhost:8082"
TOPIC = "user-gateway"
SERVICES = ["service-a-container", "service-b-container", "service-c-container", "kafka-broker", "kafka-init"]
if (ROOT / "kafka-consumer" / "Dockerfile").exists():       # started only once its folder exists
    SERVICES.append("kafka-consumer")
KAFKA_BIN = ["docker", "compose", "exec", "-T", "kafka-broker", "/opt/kafka/bin"]

os.system("")                                               # turns on ANSI colors in Windows terminals
sys.stdout.reconfigure(line_buffering=True)                 # keep our lines in order with docker/pytest output
GREEN, RED, YELLOW, BLUE, DIM, BOLD, RESET = (f"\033[{c}m" for c in (32, 31, 33, 34, 2, 1, 0))


def step(title):
    print(f"\n{BOLD}{BLUE}== {title} =={RESET}")


def info(message):
    print(f"{DIM}   {message}{RESET}")


def run(*cmd, capture=False):
    info("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=capture)


class Checks:
    def __init__(self):
        self.passed, self.failed = 0, []

    def check(self, name, ok, detail=""):
        mark = f"{GREEN}[PASS]{RESET}" if ok else f"{RED}[FAIL]{RESET}"
        print(f"   {mark} {name}" + (f"  {DIM}{detail}{RESET}" if detail else ""))
        if ok: self.passed += 1
        else: self.failed.append(name)

    def summary(self):
        colour = GREEN if not self.failed else RED
        print(f"\n{BOLD}{colour}{self.passed} passed, {len(self.failed)} failed{RESET}")
        for name in self.failed:
            print(f"   {RED}- {name}{RESET}")
        return not self.failed


def call(method, url, **kwargs):
    """HTTP call that prints a one-line trace and never raises."""
    try:
        response = httpx.request(method, url, timeout=30, **kwargs)
    except httpx.HTTPError as e:
        print(f"   {RED}{method} {url} -> {type(e).__name__}{RESET}")
        return None
    colour = GREEN if response.status_code < 400 else YELLOW
    print(f"   {colour}{method} {url.removeprefix('http://')} -> {response.status_code}{RESET}"
          f"  {DIM}{response.text[:120]}{RESET}")
    return response


def read_events():
    """Every event published on the topic so far, as dicts."""
    result = run(*KAFKA_BIN[:-1], f"{KAFKA_BIN[-1]}/kafka-console-consumer.sh", "--bootstrap-server",
                 "localhost:9092", "--topic", TOPIC, "--from-beginning", "--timeout-ms", "5000", capture=True)
    events = []
    for line in result.stdout.splitlines():
        try: events.append(json.loads(line))
        except ValueError: pass
    return events


# --- commands ---

def up(_=None):
    step("Starting containers")
    if run("docker", "compose", "up", "-d", "--build", *SERVICES).returncode != 0:
        sys.exit(f"{RED}docker compose failed: is Docker Desktop running?{RESET}")
    step("Waiting for ServiceA (it starts once Kafka is ready)")
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            if httpx.get(f"{A}/docs", timeout=2).status_code == 200:
                print(f"   {GREEN}ServiceA is up{RESET}")
                return
        except httpx.HTTPError:
            pass
        print(f"{DIM}   .{RESET}", end="", flush=True)
        time.sleep(3)
    sys.exit(f"\n{RED}ServiceA did not answer within 3 minutes: try `python demo.py logs service-a-container`{RESET}")


def down(_=None):
    step("Stopping containers")
    run("docker", "compose", "down")


def ps(_=None):
    run("docker", "compose", "ps", "-a")


def logs(args):
    run("docker", "compose", "logs", "-f", *([args.service] if args.service else []))


def unit_tests(_=None):
    step("Unit tests (no Docker needed)")
    return run(sys.executable, "-m", "pytest", "-q").returncode == 0


def live_checks(_=None):
    """Talk to the running containers and check the behaviour end to end."""
    checks = Checks()
    run_id = uuid.uuid4().hex[:6]                           # unique per run: old events don't interfere
    ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
    first, second = f"alice-{run_id}@example.com", f"bob-{run_id}@example.com"

    step("Sign-in")
    r = call("POST", f"{A}/sign-in", json={"email": first, "password": "Secret#123", "ip_address": ip})
    checks.check("valid sign-in is received", r is not None and r.status_code == 200)
    r = call("POST", f"{A}/sign-in", json={"email": second, "ip_address": ip})
    checks.check("same IP again is still received", r is not None and r.status_code == 200)
    r = call("POST", f"{A}/sign-in", json={"email": "not-an-email", "ip_address": ip})
    checks.check("invalid email is rejected (422)", r is not None and r.status_code == 422)
    r = call("POST", f"{A}/sign-in", json={"email": first})
    checks.check("missing IP is rejected (422)", r is not None and r.status_code == 422)

    step(f"Kafka events on {TOPIC}")
    time.sleep(2)                                           # send() is buffered: give it a moment
    events = read_events()
    emails = [e.get("email") for e in events]
    checks.check("first sign-in was published once", emails.count(first) == 1, f"{len(events)} events in total")
    checks.check("same IP within 60 s was not published", emails.count(second) == 0)
    checks.check("invalid sign-ins were not published", "not-an-email" not in emails)

    step("Part 1 endpoints")
    r = call("POST", f"{A}/resolve-ip-list", json=["8.8.8.8", "1.1.1.1"])
    checks.check("resolve-ip-list answers", r is not None and r.status_code == 200)
    r = call("GET", f"{A}/")
    checks.check("get-all answers", r is not None and r.status_code == 200)
    r = call("GET", f"{B}/clusters")
    checks.check("geo clusters answer", r is not None and r.status_code == 200)

    return checks.summary()


def sign_in(args):
    step("Sign-in")
    body = {"email": args.email, "ip_address": args.ip}
    if args.password: body["password"] = args.password
    call("POST", f"{A}/sign-in", json=body)


def events(_=None, last=10):
    step(f"Events on {TOPIC} (last {last})")
    found = read_events()
    for event in found[-last:]:
        print(f"   {json.dumps(event)}")
    print(f"   {DIM}{len(found)} events stored in total{RESET}")


def topic_offset():
    """How many events the broker has stored on the topic (end offset, summed over partitions)."""
    result = run(*KAFKA_BIN[:-1], f"{KAFKA_BIN[-1]}/kafka-get-offsets.sh",
                 "--bootstrap-server", "localhost:9092", "--topic", TOPIC, capture=True)
    try: return sum(int(line.rsplit(":", 1)[1]) for line in result.stdout.split())   # "user-gateway:0:42"
    except (ValueError, IndexError): return None


async def _send_all(bodies):
    """Fire every sign-in at the same time; return (status, seconds) per request."""
    async with httpx.AsyncClient(timeout=30) as client:
        async def one(body):
            start = time.perf_counter()
            try: status = (await client.post(f"{A}/sign-in", json=body)).status_code
            except httpx.HTTPError: status = None
            return status, time.perf_counter() - start
        return await asyncio.gather(*(one(body) for body in bodies))


def burst(bodies):
    started = time.perf_counter()
    results = asyncio.run(_send_all(bodies))
    total = time.perf_counter() - started
    ms = sorted(seconds * 1000 for _, seconds in results)
    statuses = [status for status, _ in results]
    print(f"   {len(bodies)} requests in {total * 1000:.0f} ms   "
          f"latency min {ms[0]:.0f} / avg {sum(ms) / len(ms):.0f} / p95 {ms[int(len(ms) * 0.95) - 1]:.0f} "
          f"/ max {ms[-1]:.0f} ms")
    print(f"   status codes: { {s: statuses.count(s) for s in set(statuses)} }")
    return statuses, ms


def load_test(args=None):
    """Many sign-ins at once: ServiceA answers fast, Kafka stores every event, the throttle still holds."""
    count = getattr(args, "count", 50)
    checks = Checks()
    run_id = uuid.uuid4().hex[:6]
    a, b = random.randint(0, 255), random.randint(0, 255)
    bodies = [{"email": f"user{i}-{run_id}@example.com", "ip_address": f"10.{a}.{b}.{i + 1}"} for i in range(count)]

    step(f"Load: {count} sign-ins from {count} different IPs, all at once")
    before = topic_offset()
    info(f"events stored on {TOPIC} before: {before}")
    statuses, ms = burst(bodies)
    checks.check(f"all {count} answered 200", statuses.count(200) == count)
    checks.check("p95 latency under 1 s (ServiceA doesn't wait for the consumer)", ms[int(len(ms) * 0.95) - 1] < 1000)

    step("Kafka: events leaving ServiceA's producer buffer and reaching the broker")
    stored, deadline = None, time.time() + 30
    start = time.time()
    while before is not None and time.time() < deadline:
        offset = topic_offset()
        if offset is None: break
        stored = offset - before
        print(f"   +{time.time() - start:4.1f} s   {stored}/{count} events on the broker")
        if stored >= count: break
        time.sleep(1)
    checks.check(f"exactly {count} new events stored", stored == count, f"got {stored}")

    step("Same 10 IPs again, within 60 s")
    repeats = [{"email": f"again{i}-{run_id}@example.com", "ip_address": body["ip_address"]}
               for i, body in enumerate(bodies[:10])]
    statuses, _ = burst(repeats)
    checks.check("all 10 still answered 200", statuses.count(200) == 10)
    time.sleep(2)
    after = topic_offset()
    known = before is not None and after is not None
    checks.check("none of them was published", known and after - before == count,
                 f"{after - before if known else '?'} new events in total")

    step("Consumer groups (LAG = events stored but not processed yet)")
    run(*KAFKA_BIN[:-1], f"{KAFKA_BIN[-1]}/kafka-consumer-groups.sh",
        "--bootstrap-server", "localhost:9092", "--describe", "--all-groups")

    step("ServiceA log lines about Kafka during the load")
    lines = run("docker", "compose", "logs", "--since", "2m", "--no-log-prefix", "service-a-container",
                capture=True).stdout.splitlines()
    kafka_lines = [l for l in lines if "kafka" in l.lower() or "ERROR" in l or "publish" in l]
    for line in kafka_lines[-15:]:
        print(f"   {RED if 'ERROR' in line else DIM}{line}{RESET}")
    if not kafka_lines:
        print(f"   {GREEN}no Kafka warnings or errors logged{RESET}")

    return checks.summary()


def watch(_=None):
    step(f"Live events on {TOPIC} (Ctrl+C to stop)")
    run(*KAFKA_BIN[:-1], f"{KAFKA_BIN[-1]}/kafka-console-consumer.sh",
        "--bootstrap-server", "localhost:9092", "--topic", TOPIC)


def everything(_=None):
    up()
    tests_ok = unit_tests()
    live_ok = live_checks()
    events()
    load_ok = load_test()
    step("Recent ServiceA logs")
    run("docker", "compose", "logs", "--tail", "15", "service-a-container")
    step("Result")
    print(f"   unit tests:  {GREEN + 'OK' if tests_ok else RED + 'FAILED'}{RESET}")
    print(f"   live checks: {GREEN + 'OK' if live_ok else RED + 'FAILED'}{RESET}")
    print(f"   load test:   {GREEN + 'OK' if load_ok else RED + 'FAILED'}{RESET}")
    print(f"   {DIM}containers are still running: `python demo.py logs` to follow, `python demo.py down` to stop{RESET}")
    sys.exit(0 if tests_ok and live_ok and load_ok else 1)


def main():
    parser = argparse.ArgumentParser(description="Start the containers, run checks, look at logs.")
    commands = parser.add_subparsers(dest="command")
    for name, func, text in [
        ("all", everything, "start containers, unit tests, live checks, events, logs (default)"),
        ("up", up, "build and start the containers, wait until ServiceA answers"),
        ("down", down, "stop and remove the containers (Kafka events are kept)"),
        ("ps", ps, "show the containers and their health"),
        ("test", unit_tests, "run the unit tests only (no Docker needed)"),
        ("check", live_checks, "run the live checks against running containers"),
        ("events", events, f"print the last events published on {TOPIC}"),
        ("watch", watch, "print new events live"),
    ]:
        commands.add_parser(name, help=text).set_defaults(func=func)

    log_parser = commands.add_parser("logs", help="follow the logs (optionally of one service)")
    log_parser.add_argument("service", nargs="?")
    log_parser.set_defaults(func=logs)

    load_parser = commands.add_parser("load", help="many sign-ins at once, then follow them through Kafka")
    load_parser.add_argument("--count", type=int, default=50)
    load_parser.set_defaults(func=load_test)

    sign_in_parser = commands.add_parser("sign-in", help="send one sign-in")
    sign_in_parser.add_argument("--email", default="alice@example.com")
    sign_in_parser.add_argument("--ip", default="1.2.3.4")
    sign_in_parser.add_argument("--password")
    sign_in_parser.set_defaults(func=sign_in)

    args = parser.parse_args()
    result = getattr(args, "func", everything)(args)
    if result is False:
        sys.exit(1)


if __name__ == "__main__":
    main()
