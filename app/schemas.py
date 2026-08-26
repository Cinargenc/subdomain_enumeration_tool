from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class EnumerateRequest(BaseModel):
    domain: str = Field(..., examples=["example.com"])
    wordlist: Optional[list[str]] = Field(
        default=None,
        description="Verilmezse sunucudaki varsayılan wordlist.txt kullanılır."
    )
    record_types: list[str] = Field(default=["A", "AAAA", "CNAME"])
    concurrency: int = Field(default=50, ge=1, le=500)
    qps: float = Field(default=20, ge=1, le=200, description="Saniyedeki maksimum DNS sorgusu")
    nameservers: Optional[list[str]] = Field(default=None, description="Özel DNS resolver IP'leri")
    detect_wildcards: bool = True


class SubdomainOut(BaseModel):
    id: int
    subdomain: str
    record_type: str
    ip_or_target: str
    cname_chain: Optional[str] = None
    is_wildcard_match: bool
    is_new: bool
    discovered_at: datetime

    class Config:
        from_attributes = True


class ScanOut(BaseModel):
    id: int
    domain: str
    wordlist_size: int
    concurrency: int
    qps: float
    wildcard_detected: bool
    wildcard_ip: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    total_checked: int
    total_found: int

    class Config:
        from_attributes = True


class ScanResultOut(BaseModel):
    scan: ScanOut
    results: list[SubdomainOut]
