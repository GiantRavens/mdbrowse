"""mdb doctor — network/DNS status for a host, decoded.

Born from the quantum.com investigation: a corporate VPN's split-DNS rule
black-holed one domain while everything else worked, and diagnosing it
took a resolver-layer archaeology session. This command runs that
archaeology in two seconds and names the fix:

  system resolver  (getaddrinfo, 3s cap — what Chromium and Python use)
  direct DNS       (dig straight at a public resolver — bypasses the OS)
  scoped claims    (scutil --dns rules claiming this domain — the receipt)
  TCP reach        (connect to the resolved address — is the host up?)

The verdict cross-reads them: hang + scoped claim + direct answer is the
VPN split-DNS signature; fail + direct answer is a broken local resolver;
ok + no TCP is a dead or firewalled host.
"""

import re
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

from .capture import _dns_preflight


def _host_of(target: str) -> str:
    t = target.strip()
    if "://" in t:
        return urlparse(t).hostname or t
    return t.split("/")[0].split(":")[0]


def _dig(host: str):
    """Direct DNS answer, bypassing the system resolver."""
    try:
        r = subprocess.run(["dig", "+short", "+time=2", "+tries=1", host, "A"],
                           capture_output=True, text=True, timeout=6)
        ips = [l.strip() for l in r.stdout.split("\n")
               if re.fullmatch(r"[\d.]+", l.strip())]
        return ips
    except Exception:
        return None


def _scoped_claims(host: str):
    """scutil --dns resolver entries whose domain claims this host."""
    try:
        out = subprocess.run(["scutil", "--dns"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:
        return []
    claims, domain, servers = [], None, []
    for line in out.split("\n"):
        m = re.match(r"resolver #\d+", line.strip())
        if m:
            if domain and (host == domain or host.endswith("." + domain)):
                claims.append((domain, servers))
            domain, servers = None, []
            continue
        dm = re.search(r"domain\s*:\s*(\S+)", line)
        if dm:
            domain = dm.group(1)
        nm = re.search(r"nameserver\[\d+\]\s*:\s*(\S+)", line)
        if nm:
            servers.append(nm.group(1))
    if domain and (host == domain or host.endswith("." + domain)):
        claims.append((domain, servers))
    return claims


def _tcp(ip: str, port: int, timeout: float = 3.0):
    t0 = time.monotonic()
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return time.monotonic() - t0
    except Exception:
        return None


def run(target: str) -> int:
    host = _host_of(target)
    print(f"mdb doctor — {host}\n")

    is_ip = bool(re.fullmatch(r"[\d.]+", host))

    # 1. system resolver (the one Chromium, Python, and Safari all use)
    t0 = time.monotonic()
    verdict = _dns_preflight(host, 3.0)
    dt = time.monotonic() - t0
    label = {"ok": f"answers ({dt:.2f}s)",
             "hang": "HANGS (>3s — query swallowed)",
             "fail": "no answer (NXDOMAIN-style failure)"}[verdict]
    print(f"  system resolver   {label}")

    # 2. direct DNS, bypassing the OS layer entirely
    ips = None
    if not is_ip:
        ips = _dig(host)
        if ips is None:
            print("  direct DNS        (dig unavailable)")
        elif ips:
            print(f"  direct DNS        answers: {', '.join(ips[:4])}")
        else:
            print("  direct DNS        no A records")
    else:
        ips = [host]

    # 3. scoped resolver claims — the split-DNS receipt
    claims = _scoped_claims(host)
    for dom, servers in claims:
        print(f"  scoped resolver   CLAIMS '{dom}' → {', '.join(servers)}")
        for ns in servers:
            reach = _tcp(ns, 53, 1.5)
            state = f"reachable ({reach:.2f}s)" if reach is not None else "UNREACHABLE"
            print(f"                    nameserver {ns}: {state}")

    # 4. can we actually reach the host?
    if ips:
        for port in (443, 80):
            reach = _tcp(ips[0], port, 3.0)
            state = f"connects ({reach:.2f}s)" if reach is not None else "no connection"
            print(f"  tcp {ips[0]}:{port:<4} {state}")
            if reach is not None:
                break

    # verdict
    print()
    if verdict == "hang" and claims:
        dom = claims[0][0]
        print(f"VERDICT: split-DNS. A scoped resolver claims '{dom}' for "
              f"nameservers that don't respond — the signature of a VPN "
              f"(GlobalProtect etc.) whose tunnel is down. Every system-"
              f"resolver client (mdb, Safari, curl) will hang on this domain.")
        print("FIX: connect the VPN, or remove the claim (after uninstalling "
              "the VPN client, REBOOT — orphaned NetworkExtension configs "
              "hold the resolver entry until then).")
        return 1
    if verdict == "hang":
        print("VERDICT: the system resolver swallows this name with no scoped "
              "claim visible — suspect a local DNS filter or firewall.")
        return 1
    if verdict == "fail" and ips:
        print("VERDICT: direct DNS answers but the system resolver does not — "
              "local resolver misconfiguration.")
        return 1
    if verdict == "ok" and ips:
        print("VERDICT: name resolution healthy; "
              + ("host reachable." if _tcp(ips[0], 443, 2.0) or _tcp(ips[0], 80, 2.0)
                 else "but the host itself is not accepting connections."))
        return 0
    print("VERDICT: name does not resolve anywhere — likely a dead or "
          "mistyped domain.")
    return 1


def doctor_cli(argv) -> int:
    if not argv:
        print("usage: mdb doctor HOST_OR_URL", file=sys.stderr)
        return 2
    return run(argv[0])
