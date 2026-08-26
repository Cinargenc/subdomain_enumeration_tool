import csv
import io
import json
import os
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import init_db, get_session, Scan, SubdomainResult
from app.schemas import EnumerateRequest, ScanOut, ScanResultOut, SubdomainOut
from app.dns_recon import enumerate_subdomains

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_WORDLIST_PATH = os.path.join(BASE_DIR, "wordlist.txt")

#API uygulamasını oluşturuyor
app = FastAPI( 
    title="Subdomain Enumeration & DNS Recon API",
    description="Bir alan adına ait alt alan adlarını eşzamanlı olarak keşfeden, "
                "wildcard DNS tespiti yapan ve sonuçları kalıcı olarak saklayan API.",
    version="1.0.0",
)

#CORS Backend-frontend iletişimini kolaylaştırır.Örneğin localhost:3000 ile localhost:8000 iletişim kurabilir
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], #her originden gelen isteğe izin ver
    allow_methods=["*"],
    allow_headers=["*"],
)


#Fast API çalıştığında veritabanı çalıştırılır
@app.on_event("startup")
async def on_startup():
    await init_db()

#kullanıcı kendisi wordlist yuklemezse default wordlist kullanılır
def load_default_wordlist() -> list[str]:
    if not os.path.exists(DEFAULT_WORDLIST_PATH):
        return ["www", "mail", "ftp", "api", "dev"]
    with open(DEFAULT_WORDLIST_PATH, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

#index.html style.css gibi statik dosyaları FastAPI ye bağlıyor
static_dir = os.path.join(BASE_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Subdomain Enumeration API çalışıyor. /docs adresine gidin."}


# ---------------------------------------------------------------------------
# Enumerate
# ---------------------------------------------------------------------------
@app.post("/enumerate", response_model=ScanResultOut)
#Bu domain üzerinde subdomain enumeration başlat.
async def enumerate_endpoint(req: EnumerateRequest, session: AsyncSession = Depends(get_session)):
    domain = req.domain.strip().lower().rstrip(".") #domain temizleme
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Geçerli bir alan adı giriniz (ör. example.com)")

    #wordlist seçimi
    wordlist = req.wordlist if req.wordlist else load_default_wordlist()
    if not wordlist:
        raise HTTPException(status_code=400, detail="Wordlist boş olamaz")

    #kullanıcı girişine göre yeni bir scan oluştur
    scan = Scan(
        domain=domain,
        wordlist_size=len(wordlist),
        concurrency=req.concurrency,
        qps=req.qps,
        started_at=datetime.utcnow(),
    )
    session.add(scan)
    await session.flush()  # scan.id üretmek için

    #dns_recon.py dosyası ile ilişki kurma
    started = datetime.utcnow()
    outcome = await enumerate_subdomains(
        domain=domain,
        wordlist=wordlist,
        record_types=req.record_types,
        concurrency=req.concurrency,
        qps=req.qps,
        nameservers=req.nameservers,
        detect_wildcards=req.detect_wildcards,
    )
    finished = datetime.utcnow()

    # Önceki tarama ile karşılaştırma (aynı domain, bu taramadan önceki en son tamamlanan tarama)
    prev_scan_id_result = await session.execute(
        select(Scan.id)
        .where(Scan.domain == domain, Scan.id != scan.id, Scan.finished_at.isnot(None))
        .order_by(Scan.id.desc())
        .limit(1)
    )
    prev_scan_id = prev_scan_id_result.scalar_one_or_none()
    prev_subdomains = set()
    if prev_scan_id:
        prev_rows = await session.execute(
            select(SubdomainResult.subdomain).where(SubdomainResult.scan_id == prev_scan_id)
        )
        prev_subdomains = {row[0] for row in prev_rows.all()}

    seen_subdomains = set()
    for r in outcome["results"]:#dns sonuçlarının veritabanına yazılması
        seen_subdomains.add(r.subdomain)
        db_row = SubdomainResult( #database modeli oluşturuluyor
            scan_id=scan.id,
            subdomain=r.subdomain,
            record_type=r.record_type,
            ip_or_target=r.value,
            cname_chain=",".join(r.cname_chain) if r.cname_chain else None,
            is_wildcard_match=r.is_wildcard_match,
            is_new=(bool(prev_scan_id) and r.subdomain not in prev_subdomains), #Önceki taramada yoksa yeni subdomain olarak işaretle.
            discovered_at=datetime.utcnow(),
        )
        session.add(db_row)

    #tarama sonrası istatistkler kaydediliyor
    scan.finished_at = finished
    scan.duration_seconds = int((finished - started).total_seconds())
    scan.total_checked = outcome["total_checked"]
    scan.total_found = len(seen_subdomains)
    scan.wildcard_detected = bool(outcome["wildcard_ip"]) #wildcard bilgisi
    scan.wildcard_ip = outcome["wildcard_ip"]

    await session.commit()
    await session.refresh(scan)

    #sonuçlar veritabanından tekrar okunuyor
    result_rows = await session.execute(
        select(SubdomainResult).where(SubdomainResult.scan_id == scan.id).order_by(SubdomainResult.subdomain)
    )
    results = result_rows.scalars().all()

    return ScanResultOut(scan=ScanOut.model_validate(scan), results=[SubdomainOut.model_validate(r) for r in results])


# ---------------------------------------------------------------------------
# Results / listing
# ---------------------------------------------------------------------------
@app.get("/results", response_model=list[SubdomainOut])
async def get_results( #Bu endpoint kayıtlı sonuçları getiriyor.
    scan_id: int | None = Query(default=None),
    domain: str | None = Query(default=None),
    include_wildcard_matches: bool = Query(default=True), #Wildcard sonuçlarını filtreleme
    session: AsyncSession = Depends(get_session),
):
    query = select(SubdomainResult)
    if scan_id is not None:
        query = query.where(SubdomainResult.scan_id == scan_id)
    elif domain:
        subq = select(Scan.id).where(Scan.domain == domain.strip().lower())
        query = query.where(SubdomainResult.scan_id.in_(subq))
    else:
        # scan_id/domain verilmezse en son taramanın sonuçlarını döndür
        last_scan = await session.execute(select(Scan.id).order_by(Scan.id.desc()).limit(1))
        last_scan_id = last_scan.scalar_one_or_none()
        if last_scan_id is None:
            return []
        query = query.where(SubdomainResult.scan_id == last_scan_id)

    if not include_wildcard_matches:
        query = query.where(SubdomainResult.is_wildcard_match.is_(False))

    query = query.order_by(SubdomainResult.subdomain)
    rows = await session.execute(query)
    return [SubdomainOut.model_validate(r) for r in rows.scalars().all()]

#Daha önce yapılmış tüm taramaları listeliyor.
@app.get("/scans", response_model=list[ScanOut])
async def list_scans(domain: str | None = None, session: AsyncSession = Depends(get_session)):
    query = select(Scan).order_by(Scan.id.desc())
    if domain:
        query = query.where(Scan.domain == domain.strip().lower())
    rows = await session.execute(query)
    return [ScanOut.model_validate(s) for s in rows.scalars().all()]


@app.get("/scans/{scan_id}", response_model=ScanResultOut)
async def get_scan(scan_id: int, session: AsyncSession = Depends(get_session)):
    scan = await session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Tarama bulunamadı")
    rows = await session.execute(
        select(SubdomainResult).where(SubdomainResult.scan_id == scan_id).order_by(SubdomainResult.subdomain)
    )
    results = rows.scalars().all()
    return ScanResultOut(scan=ScanOut.model_validate(scan), results=[SubdomainOut.model_validate(r) for r in results])


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
#Sonuçları csv veya json formatında kaydetme
@app.get("/export/csv")
async def export_csv(scan_id: int, session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(SubdomainResult).where(SubdomainResult.scan_id == scan_id).order_by(SubdomainResult.subdomain)
    )
    results = rows.scalars().all()
    if not results:
        raise HTTPException(status_code=404, detail="Bu tarama için kayıt bulunamadı")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["subdomain", "record_type", "ip_or_target", "cname_chain", "is_wildcard_match", "is_new", "discovered_at"])
    for r in results:
        writer.writerow([r.subdomain, r.record_type, r.ip_or_target, r.cname_chain or "", r.is_wildcard_match, r.is_new, r.discovered_at])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=scan_{scan_id}.csv"},
    )


@app.get("/export/json")
async def export_json(scan_id: int, session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(SubdomainResult).where(SubdomainResult.scan_id == scan_id).order_by(SubdomainResult.subdomain)
    )
    results = rows.scalars().all()
    if not results:
        raise HTTPException(status_code=404, detail="Bu tarama için kayıt bulunamadı")
    payload = [SubdomainOut.model_validate(r).model_dump(mode="json") for r in results]
    return StreamingResponse(
        io.BytesIO(json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=scan_{scan_id}.json"},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
