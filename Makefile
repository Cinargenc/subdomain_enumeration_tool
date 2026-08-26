# Subdomain Recon — Makefile
# Kullanım: make <hedef>
# Örn:      make install   /   make run   /   make docker-up

PYTHON        ?= python3
VENV_DIR      ?= venv
PIP           = $(VENV_DIR)/bin/pip
UVICORN       = $(VENV_DIR)/bin/uvicorn
HOST          ?= 0.0.0.0
PORT          ?= 8000

.PHONY: help venv install run dev clean reset-db docker-build docker-up docker-down docker-logs freeze

help: ## Kullanılabilir komutları listeler
	@echo "Kullanılabilir komutlar:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

venv: ## Sanal ortam (venv) oluşturur
	$(PYTHON) -m venv $(VENV_DIR)
	@echo "Sanal ortam oluşturuldu: $(VENV_DIR)"

install: venv ## Sanal ortamı kurar ve bağımlılıkları yükler
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "Kurulum tamamlandı. Sunucuyu başlatmak için: make run"

run: ## Sunucuyu başlatır (production benzeri, --reload olmadan)
	$(UVICORN) app.main:app --host $(HOST) --port $(PORT)

dev: ## Sunucuyu geliştirme modunda başlatır (--reload ile, kod değişince otomatik yeniden başlar)
	$(UVICORN) app.main:app --reload --host $(HOST) --port $(PORT)

reset-db: ## Yerel SQLite veritabanını sıfırlar (data/subrecon.db siler)
	rm -f data/subrecon.db
	@echo "Veritabanı sıfırlandı."

freeze: ## Kurulu paketleri requirements.txt formatında yazdırır (kontrol amaçlı)
	$(PIP) freeze

clean: ## venv, __pycache__ ve geçici dosyaları temizler
	rm -rf $(VENV_DIR)
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "Temizlik tamamlandı."

docker-build: ## Docker image'ını derler
	docker compose build

docker-up: ## Docker container'ı ayağa kaldırır (arka planda)
	docker compose up -d
	@echo "API şu adreste: http://localhost:$(PORT)"

docker-down: ## Docker container'ı durdurur
	docker compose down

docker-logs: ## Docker container loglarını takip eder
	docker compose logs -f
