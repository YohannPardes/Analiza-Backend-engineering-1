"""
Stress test for the running stack (A -> C -> providers -> B).

Phases:
  1. one IP through Service C                 -> is the chain alive?
  2. a concurrent burst through Service C     -> rate limiting + provider failover
  3. a POST /resolve-ip-list through Service A
  4. GET /generate-geo-clusters on Service B  -> clustering over everything stored

Run it with `make stress` (or `make stress IPS=60 CONCURRENCY=20`).
"""
import argparse
import asyncio
import ipaddress
import json
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def load_ips(count, seed=None):
    """Use test_ips.json when present, otherwise generate random public IPs."""
    pool_file = ROOT / "test_ips.json"
    if pool_file.exists():
        pool = json.loads(pool_file.read_text())
    else:
        rng = random.Random(seed)
        pool, seen = [], set()
        while len(pool) < count:
            ip = ipaddress.IPv4Address(rng.getrandbits(32))
            if ip.is_global and not ip.is_multicast and str(ip) not in seen:
                seen.add(str(ip))
                pool.append(str(ip))
    random.Random(seed).shuffle(pool)
    return pool[:count]


def summarize(label, results):
    """results: list of (status_code_or_None, seconds, body_or_error)"""
    codes = Counter(r[0] for r in results)
    times = sorted(r[1] for r in results)
    duplicates = sum(1 for r in results if isinstance(r[2], dict) and r[2].get("success") is False)

    print(f"\n{label}")
    print(f"  requests     : {len(results)}")
    print(f"  status codes : {dict(sorted(codes.items(), key=lambda kv: str(kv[0])))}")
    print(f"  stored ok    : {codes.get(200, 0) - duplicates}   (duplicates: {duplicates})")
    if times:
        print(f"  latency      : min {times[0]:.2f}s  median {statistics.median(times):.2f}s  "
              f"p95 {times[min(int(len(times) * 0.95), len(times) - 1)]:.2f}s  max {times[-1]:.2f}s")
    for code in sorted(c for c in codes if c not in (200, None)):
        example = next(r[2] for r in results if r[0] == code)
        print(f"  example {code}  : {str(example)[:140]}")
    unreachable = [r[2] for r in results if r[0] is None]
    if unreachable:
        print(f"  client errors: {len(unreachable)}  e.g. {unreachable[0][:140]}")


async def resolve_one(client, c_url, ip, semaphore):
    async with semaphore:
        started = time.perf_counter()
        try:
            r = await client.get(f"{c_url}/resolve-ip/{ip}")
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
            return r.status_code, time.perf_counter() - started, body
        except Exception as e:
            return None, time.perf_counter() - started, repr(e)


async def wait_until_up(urls, timeout=60):
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=3) as client:
        while time.time() < deadline:
            try:
                for url in urls:
                    await client.get(f"{url}/openapi.json")
                return True
            except Exception:
                await asyncio.sleep(1)
    return False


async def reset_memory(client, a_url, b_url):
    """Delete every stored record so a run starts from an empty memory."""
    stored = (await client.get(f"{b_url}/getAll")).json()
    for record_id in stored:
        await client.get(f"{a_url}/delete/{record_id}")
    print(f"reset: deleted {len(stored)} stored record(s)")


async def main(args):
    a_url, b_url, c_url = args.service_a, args.service_b, args.service_c

    print(f"waiting for {a_url}, {b_url}, {c_url} ...")
    if not await wait_until_up([a_url, b_url, c_url]):
        sys.exit("services are not responding - is `make up` done?")

    ips = load_ips(args.ips + args.list_size, seed=args.seed)
    burst_ips, list_ips = ips[:args.ips], ips[args.ips:]

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        if args.reset:
            await reset_memory(client, a_url, b_url)

        # --- phase 1: single request through the whole chain
        semaphore = asyncio.Semaphore(args.concurrency)
        first = await resolve_one(client, c_url, burst_ips[0], semaphore)
        summarize("phase 1 - single IP through Service C", [first])

        # --- phase 2: concurrent burst, the part the API manager has to survive
        print(f"\nphase 2 - firing {len(burst_ips)} requests at Service C, {args.concurrency} at a time ...")
        started = time.perf_counter()
        burst = await asyncio.gather(*(resolve_one(client, c_url, ip, semaphore) for ip in burst_ips))
        elapsed = time.perf_counter() - started
        summarize(f"phase 2 - burst of {len(burst_ips)} (wall clock {elapsed:.1f}s, "
                  f"{len(burst_ips) / elapsed:.1f} req/s)", list(burst))

        # --- phase 3: the batch endpoint on Service A
        print(f"\nphase 3 - POST /resolve-ip-list with {len(list_ips)} IPs ...")
        started = time.perf_counter()
        r = await client.post(f"{a_url}/resolve-ip-list", json=list_ips)
        elapsed = time.perf_counter() - started
        body = r.json()
        print(f"  status {r.status_code} in {elapsed:.1f}s")
        if isinstance(body, dict) and "failed_ip_count" in body:
            print(f"  failed {body['failed_ip_count']}/{len(list_ips)}")
            for ip, message in body["failed_ips"][:5]:
                print(f"    {ip}: {str(message)[:110]}")
        else:
            print(f"  body: {str(body)[:200]}")

        # --- phase 4: clustering over everything that got stored
        stored = (await client.get(f"{b_url}/getAll")).json()
        started = time.perf_counter()
        r = await client.get(f"{b_url}/generate-geo-clusters")
        elapsed = time.perf_counter() - started
        clusters = r.json()
        sizes = sorted((len([k for k in c if not k.endswith("_coordinates")]) for c in clusters.values()),
                       reverse=True)
        print(f"\nphase 4 - clustering {len(stored)} stored records (MST cut-off from the data)")
        print(f"  status {r.status_code} in {elapsed:.3f}s")
        print(f"  clusters     : {len(clusters)}")
        print(f"  biggest first: {sizes[:10]}{' ...' if len(sizes) > 10 else ''}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-a", default="http://localhost:8081")
    parser.add_argument("--service-b", default="http://localhost:8082")
    parser.add_argument("--service-c", default="http://localhost:8083")
    parser.add_argument("--ips", type=int, default=30, help="IPs in the concurrent burst")
    parser.add_argument("--concurrency", type=int, default=10, help="requests in flight at once")
    parser.add_argument("--list-size", type=int, default=5, help="IPs sent to /resolve-ip-list")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--reset", action="store_true", help="empty Service B's memory first")
    asyncio.run(main(parser.parse_args()))
