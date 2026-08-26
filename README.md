# Subdomain Recon — Alt Alan Adı Keşif Aracı

FastAPI + asyncio + dnspython ile geliştirilmiş, eşzamanlı ve rate-limited bir DNS
subdomain enumeration aracı. Sonuçlar SQLite'ta (PostgreSQL'e taşınabilir) saklanır,
koyu temalı bir web arayüzü ve tam bir REST API sunar.

> ⚠ **Kapsam / Etik Uyarı:** Bu aracı yalnızca sahibi olduğunuz veya açık test izni
> aldığınız alan adlarında kullanın.

## Özellikler

- **Eşzamanlı DNS çözümleme** — `asyncio` + `dns.asyncresolver`, `Semaphore` ile
  eşzamanlılık sınırı (`concurrency`)
- **Rate limiting** — token-bucket tabanlı `qps` (saniyedeki sorgu) sınırı
- **Wildcard DNS tespiti** — taramadan önce rastgele bir alt alan adı çözümlenir;
  çözümlenirse o IP wildcard olarak işaretlenir ve sonuçlarda ayrıştırılır
- **CNAME zinciri takibi** — maksimum 8 derinliğe kadar
- **Çoklu resolver desteği** — istekte özel `nameservers` listesi verilebilir
- **Önceki tarama ile karşılaştırma** — aynı domain için yeni çıkan alt alanlar `is_new` ile işaretlenir
- **A / AAAA / CNAME** kayıt tipleri
- **JSON / CSV export**, panoya kopyalama
- **Koyu temalı web arayüzü** (`/`) — domain girip "Start Scan" ile tarama başlatma,
  istatistikler, sonuç tablosu, dışa aktarma butonları
- **Docker & docker-compose** desteği (PostgreSQL'e geçiş yorum satırlarıyla hazır)

## Kurulum (yerel)

```bash
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Tarayıcıda `http://localhost:8000` adresine gidin. API dokümantasyonu (Swagger):
`http://localhost:8000/docs`.

## Docker ile çalıştırma

```bash
docker compose up --build
```

## API Uç Noktaları

| Method | Path            | Açıklama                                             |
|--------|-----------------|-------------------------------------------------------|
| POST   | `/enumerate`    | Yeni bir keşif taraması başlatır ve sonuçları döner    |
| GET    | `/results`      | Kayıtlı sonuçları listeler (`scan_id` veya `domain` ile filtrelenebilir) |
| GET    | `/scans`        | Geçmiş taramaları listeler                             |
| GET    | `/scans/{id}`   | Belirli bir taramanın detayları ve sonuçları           |
| GET    | `/export/csv`   | Bir taramanın sonuçlarını CSV olarak indirir           |
| GET    | `/export/json`  | Bir taramanın sonuçlarını JSON olarak indirir          |
| GET    | `/health`       | Sağlık kontrolü                                        |

### Örnek istek

```bash
curl -X POST http://localhost:8000/enumerate \
  -H "Content-Type: application/json" \
  -d '{
        "domain": "example.com",
        "concurrency": 50,
        "qps": 20,
        "record_types": ["A", "AAAA", "CNAME"],
        "detect_wildcards": true
      }'
```

`wordlist` alanı verilmezse, sunucudaki `wordlist.txt` (200+ yaygın alt alan adı)
kullanılır. Kendi listenizi göndermek isterseniz `"wordlist": ["www", "api", "dev", ...]`
şeklinde ekleyin.

## PostgreSQL'e Geçiş

Varsayılan olarak SQLite kullanılır (`./data/subrecon.db`). PostgreSQL kullanmak için:

1. `requirements.txt` dosyasına `asyncpg` ekleyin.
2. Ortam değişkenini ayarlayın:
   ```
   DATABASE_URL=postgresql+asyncpg://kullanici:sifre@localhost:5432/subrecon
   ```
3. `docker-compose.yml` içindeki yorumlanmış `db` servisini açın.

## Proje Yapısı

```
subrecon/
├── app/
│   ├── main.py        # FastAPI endpoint'leri
│   ├── dns_recon.py    # Async DNS keşif motoru (eşzamanlılık, rate-limit, wildcard, CNAME)
│   ├── db.py           # SQLAlchemy modelleri (Scan, SubdomainResult)
│   └── schemas.py       # Pydantic request/response modelleri
├── static/
│   └── index.html      # Koyu temalı web arayüzü
├── wordlist.txt         # Varsayılan alt alan adı kelime listesi
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Zor Kısımların Çözümü

- **Yüksek hacimli eşzamanlı sorgu + rate-limit**: `asyncio.Semaphore(concurrency)`
  aynı anda kaç sorgunun uçtuğunu sınırlar; ayrı bir `RateLimiter` (token-bucket)
  her sorgu başlamadan önce `qps` sınırına göre bekler. İkisi birlikte, DNS
  sunucusunu boğmadan yüksek verim sağlar.
- **Wildcard DNS**: Tarama başlamadan önce var olmayan rastgele bir alt alan adı
  (`<rastgele20karakter>.domain`) çözümlenmeye çalışılır. Çözümlenirse, o alan adı
  wildcard DNS kullanıyor demektir; dönen IP(ler) `wildcard_ip` olarak kaydedilir ve
  taramadaki her sonuç bu IP ile eşleşiyorsa `is_wildcard_match=true` işaretlenir
  (varsayılan olarak gösterilir ama arayüzde tek tıkla filtrelenebilir).
- **Hata yönetimi**: `NXDOMAIN`, `NoAnswer`, `Timeout` gibi beklenen DNS
  istisnaları sessizce atlanır (`None` döner); beklenmeyen istisnalar da
  yakalanıp loglanmadan geçilir, böylece tek bir bozuk kayıt tüm taramayı
  düşürmez.
