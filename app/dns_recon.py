"""
DNS Recon Engine
================
- asyncio + dnspython (dns.asyncresolver) ile eşzamanlı çözümleme
- Semaphore tabanlı eşzamanlılık sınırı + token-bucket rate limit (qps)
- Wildcard DNS tespiti: rastgele/var olmayan bir alt alan adı önceden çözümlenir;
  çözümlenirse o IP "wildcard IP" olarak işaretlenir ve sonuçlar buna göre etiketlenir.
- CNAME zincirlerini belirli bir derinliğe kadar takip eder.
- Birden fazla DNS resolver (nameserver) desteği.
"""
import asyncio
import random
import string
import time
from dataclasses import dataclass, field
from typing import Optional

import dns.asyncresolver
import dns.resolver
import dns.exception


DEFAULT_RECORD_TYPES = ["A", "AAAA", "CNAME"]  
MAX_CNAME_DEPTH = 8
#A->ipv4 AAAA->ipv6 CNAME->www.example.com → example.com(başka bir domain gösterir

@dataclass
class ResolutionResult:
    subdomain: str
    record_type: str
    value: str                 # IP adresi ya da CNAME hedefi
    cname_chain: list = field(default_factory=list)
    is_wildcard_match: bool = False # Bu IP wildcard DNS sonucundan mı geldi?
#subdomain:api.example.com record_type:A value:192.168.1.10

class RateLimiter:
    #Basit token-bucket rate limiter: saniyede en fazla `qps` sorgu başlatımına izin verir.

    def __init__(self, qps: float):
        self.qps = max(qps, 0.1) #qps=20 için 1/20=0.05 saniyede bir sorgu başlat
        self._interval = 1.0 / self.qps
        self._lock = asyncio.Lock()
        self._next_time = time.monotonic()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            wait = self._next_time - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_time = max(now, self._next_time) + self._interval


def _random_label(length: int = 20) -> str: #a91k2m8x7q3z5p1n4abc.example.com şeklinde rastgele bir subdomain oluşturur
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _build_resolver(nameservers: Optional[list[str]], timeout: float, lifetime: float) -> dns.asyncresolver.Resolver:
    resolver = dns.asyncresolver.Resolver() #kullanılacak dns sunucusu değiştirilebilir nameservers=["8.8.8.8"]
    if nameservers:
        resolver.nameservers = nameservers
    resolver.timeout = timeout
    resolver.lifetime = lifetime
    return resolver


async def _resolve_one_type(resolver: dns.asyncresolver.Resolver, name: str, rtype: str):
    #Tek bir kayıt tipi için çözümleme dener. Bulunamazsa None döner (sessizce atlanır).
    try: #example.com için A kaydı nedir? 192.168.1.20 olabilir ve bunu liste olarak döndürür
        answer = await resolver.resolve(name, rtype)
        return [str(r).rstrip(".") for r in answer]
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.exception.Timeout,
        dns.resolver.LifetimeTimeout, #hataların yönetilmesi ile programın çökmesinin önlenmesi
    ):
        return None
    except Exception:
        # Beklenmedik DNS hataları da sessizce atlanır
        return None


async def resolve_with_cname_chain(resolver: dns.asyncresolver.Resolver, name: str, record_types: list[str]):
    #Bir isim için sırayla CNAME zincirini takip eder, sonunda A/AAAA kayıtlarını çözer.
    results: list[ResolutionResult] = []
    chain: list[str] = []
    current = name

    # 1) CNAME zincirini takip et
    if "CNAME" in record_types:
        depth = 0
        seen = set()
        while depth < MAX_CNAME_DEPTH:
            cname_vals = await _resolve_one_type(resolver, current, "CNAME")
            if not cname_vals:
                break
            target = cname_vals[0]
            if target in seen: #kötü yapılandırılmıs bır dns sistemi varsa sonsuz döngü olusturmaması için
                break
            seen.add(target)
            chain.append(target)
            current = target
            depth += 1

    # 2) Zincirin ucunda (veya doğrudan) A/AAAA kayıtlarını çözümle
    for rtype in ("A", "AAAA"):
        if rtype not in record_types:
            continue
        vals = await _resolve_one_type(resolver, current, rtype)
        if vals:
            for v in vals:
                results.append(ResolutionResult(
                    subdomain=name,
                    record_type=rtype,
                    value=v,
                    cname_chain=chain,
                ))  # subdomain: www.example.com
                    # type: A
                    # value: 203.0.113.20->ip adresi çözümlenebilmişse
                    # cname_chain:
                    # cdn.example.net  

    # Eğer sadece CNAME istenmiş ve A/AAAA çözümlenememişse, CNAME'i kayıt olarak ekle
    if chain and not results and "CNAME" in record_types:
        results.append(ResolutionResult(
            subdomain=name,
            record_type="CNAME",
            value=chain[-1],
            cname_chain=chain,
        ))

    return results


async def detect_wildcard(resolver: dns.asyncresolver.Resolver, domain: str) -> Optional[set]:
    
    #Var olmayan rastgele bir alt alan adını çözümlemeyi dener. Eğer çözümlenirse domain wildcard DNS kullanıyor demektir -> o IP(ler) döner.Aksi halde None döner.
    
    probe = f"{_random_label()}.{domain}"
    ips = set()
    for rtype in ("A", "AAAA"):
        vals = await _resolve_one_type(resolver, probe, rtype)
        if vals:
            ips.update(vals)
    return ips or None


async def enumerate_subdomains(
    domain: str,
    wordlist: list[str],
    record_types: list[str] = None,
    concurrency: int = 50,
    qps: float = 20,
    timeout: float = 3.0,
    lifetime: float = 5.0,
    nameservers: Optional[list[str]] = None,
    detect_wildcards: bool = True,
    progress_cb=None,
):
    """
    Ana keşif fonksiyonu.

    Döner: dict(
        results=list[ResolutionResult],
        wildcard_ip=set|None,
        total_checked=int,
    )
    """
    record_types = record_types or DEFAULT_RECORD_TYPES
    resolver = _build_resolver(nameservers, timeout, lifetime)

    wildcard_ips = None
    if detect_wildcards:
        wildcard_ips = await detect_wildcard(resolver, domain)

    semaphore = asyncio.Semaphore(concurrency)
    rate_limiter = RateLimiter(qps)
    all_results: list[ResolutionResult] = []
    checked = 0
    lock = asyncio.Lock()

    async def worker(word: str): # her wordlist elemanı için bir worker oluşturur
        nonlocal checked
        fqdn = f"{word.strip()}.{domain}" if word.strip() else None
        if not fqdn:
            return
        await rate_limiter.acquire() # qps limiti ve eşzamanlılık uygulanıyor
        async with semaphore:
            try:
                res = await resolve_with_cname_chain(resolver, fqdn, record_types)
            except Exception:
                res = []
            for r in res:
                if wildcard_ips and r.value in wildcard_ips and r.record_type in ("A", "AAAA"):
                    r.is_wildcard_match = True
                all_results.append(r)
        async with lock:
            checked += 1
            if progress_cb:
                await progress_cb(checked, len(wordlist))

    tasks = [asyncio.create_task(worker(w)) for w in wordlist if w.strip()] # Her subdomain için bir asynchronous task oluşturuyor.
    if tasks:
        await asyncio.gather(*tasks)

    return {
        "results": all_results,
        "wildcard_ip": ",".join(sorted(wildcard_ips)) if wildcard_ips else None,
        "total_checked": checked,
    }

# {
#     "results": [
#         ResolutionResult(
#             subdomain="api.example.com",
#             record_type="A",
#             value="1.2.3.4"
#         )
#     ],
#     "wildcard_ip": "1.2.3.4",
#     "total_checked": 500
# }
