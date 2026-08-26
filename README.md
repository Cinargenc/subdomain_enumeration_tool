# Subdomain Recon — Alt Alan Adı Keşif Aracı

FastAPI + asyncio + dnspython ile geliştirilmiş, eşzamanlı ve rate-limited bir DNS
subdomain enumeration aracı. Sonuçlar SQLite'ta (PostgreSQL'e taşınabilir) saklanır,
koyu temalı bir web arayüzü ve tam bir REST API sunar.

> **Kapsam / Etik Uyarı:** Bu araç yalnızca sahibi olduğunuz veya güvenlik testi gerçekleştirmek için açık ve yetkili izin aldığınız alan adlarında kullanılmalıdır. Subdomain enumeration işlemi, hedef sistemlere çok sayıda DNS sorgusu göndererek dış saldırı >yüzeyi hakkında bilgi toplayabilir. Bu nedenle üçüncü taraf sistemlerde izinsiz tarama yapmak; hizmet sağlayıcının kullanım koşullarını ihlal edebileceği gibi, bulunduğunuz ülkenin ve hedef sistemin tabi olduğu yasal düzenlemeler kapsamında hukuki veya idari >sonuçlar doğurabilir. Aracı kullanmadan önce hedef domain üzerinde gerekli yetkiye sahip olduğunuzdan emin olun. Tarama sırasında kullanılan concurrency ve qps değerlerini makul seviyelerde tutarak DNS sunucuları üzerinde gereksiz yük veya hizmet kesintisi >oluşturmaktan kaçının. Elde edilen subdomain, DNS kaydı ve IP adresi gibi bilgileri yalnızca testin amacı doğrultusunda ve yetkilendirilen kapsam içerisinde kullanın.
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

## Makefile ile çalıştırma (daha kolay yol)

Yukarıdaki komutları tek tek yazmak yerine, Linux/macOS'ta (veya Windows'ta WSL /
Git Bash üzerinden) `make` kullanarak aynı işlemleri tek satırla yapabilirsiniz:

```bash
make install     # venv oluşturur + bağımlılıkları kurar
make dev         # sunucuyu --reload ile (geliştirme modunda) başlatır
make run         # sunucuyu --reload olmadan başlatır
```

Diğer kullanışlı komutlar:

```bash
make help        # tüm komutları ve açıklamalarını listeler
make reset-db    # yerel SQLite veritabanını sıfırlar
make clean       # venv ve önbellek dosyalarını temizler
make docker-up   # docker compose ile ayağa kaldırır
make docker-down # docker container'ı durdurur
make docker-logs # docker container loglarını takip eder
```

> **Not (Windows/cmd kullanıcıları):** `make` komutu varsayılan olarak Windows
> `cmd.exe`'de bulunmaz. WSL, Git Bash veya `choco install make` ile
> kurabilirsiniz. Kurmak istemiyorsanız yukarıdaki "Kurulum (yerel)" bölümündeki
> komutları elle çalıştırmaya devam edebilirsiniz — Makefile sadece bir kısayoldur,
> zorunlu değildir.

## Docker ile çalıştırma

```bash
docker compose up --build
# veya
make docker-up
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

`wordlist` alanı verilmezse, sunucudaki `wordlist.txt` (400+ yaygın alt alan adı)
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
├── Makefile             # make install / make dev / make run vb. kısayollar
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
