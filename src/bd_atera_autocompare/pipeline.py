from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .atera.api import AteraApiProvider
from .atera.export import (
    DEFAULT_ATERA_OUTPUT_PATH,
    DEFAULT_PAGE_SIZE as DEFAULT_ATERA_PAGE_SIZE,
    export_atera_csv,
)
from .bd.api import DEFAULT_BD_API_URL, BdApiProvider
from .bd.prepare import (
    DEFAULT_BD_OUTPUT_PATH,
    DEFAULT_PAGE_SIZE as DEFAULT_BD_PAGE_SIZE,
    prepare_bd_csv,
)
from .compare import (
    DEFAULT_COMPANY_ALIASES_PATH,
    DEFAULT_DEVICE_ALIASES_PATH,
    DEFAULT_DUPLICATES_OUTPUT_PATH,
    DEFAULT_EXCLUDE_COMPANY_PATH,
    DEFAULT_OUTPUT_PATH as DEFAULT_COMPARE_OUTPUT_PATH,
    compare_csvs,
)

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class PipelineSettings:
    env_file: Path = Path(".env")
    http_timeout: float = 30.0
    atera_output: Path = DEFAULT_ATERA_OUTPUT_PATH
    atera_page_size: int = DEFAULT_ATERA_PAGE_SIZE
    bd_output: Path = DEFAULT_BD_OUTPUT_PATH
    bd_api_url: str = ""
    bd_page_size: int = DEFAULT_BD_PAGE_SIZE
    bd_parent_id: str = ""
    bd_company_name: str = ""
    bd_recursive: bool = True
    bd_return_product_outdated: bool = True
    bd_include_scan_logs: bool = True
    bd_include_unprotected: bool = False
    report_output: Path = DEFAULT_COMPARE_OUTPUT_PATH
    duplicates_output: Path = DEFAULT_DUPLICATES_OUTPUT_PATH
    company_aliases: Path | None = DEFAULT_COMPANY_ALIASES_PATH
    device_aliases: Path | None = DEFAULT_DEVICE_ALIASES_PATH
    exclude_company: Path | None = DEFAULT_EXCLUDE_COMPANY_PATH


@dataclass(frozen=True)
class PipelineResult:
    atera_rows: int
    bd_rows: int
    mismatch_rows: int
    atera_output: Path
    bd_output: Path
    report_output: Path
    duplicates_output: Path


def bd_provider_from_settings(settings: PipelineSettings) -> BdApiProvider:
    provider_kwargs = {
        "env_file": settings.env_file,
        "timeout": settings.http_timeout,
        "page_size": settings.bd_page_size,
        "recursive": settings.bd_recursive,
        "return_product_outdated": settings.bd_return_product_outdated,
        "include_scan_logs": settings.bd_include_scan_logs,
        "include_unprotected": settings.bd_include_unprotected,
    }
    if settings.bd_api_url:
        provider_kwargs["api_url"] = settings.bd_api_url
    if settings.bd_parent_id:
        provider_kwargs["parent_id"] = settings.bd_parent_id
    if settings.bd_company_name:
        provider_kwargs["company_name"] = settings.bd_company_name
    return BdApiProvider.from_environment(**provider_kwargs)


def emit_status(status: StatusCallback | None, message: str) -> None:
    if status is not None:
        status(message)


def run_pipeline(
    settings: PipelineSettings = PipelineSettings(),
    *,
    status: StatusCallback | None = None,
) -> PipelineResult:
    emit_status(status, "Pulling Atera agents...")
    atera_provider = AteraApiProvider.from_environment(
        env_file=settings.env_file,
        timeout=settings.http_timeout,
        page_size=settings.atera_page_size,
    )
    atera_rows = export_atera_csv(atera_provider, settings.atera_output)
    emit_status(status, f"Wrote {atera_rows} Atera row(s) to {settings.atera_output}")

    emit_status(status, "Pulling Bitdefender endpoints...")
    bd_provider = bd_provider_from_settings(settings)
    bd_rows = prepare_bd_csv(bd_provider, settings.bd_output)
    emit_status(status, f"Wrote {bd_rows} BD row(s) to {settings.bd_output}")

    emit_status(status, "Comparing normalized CSVs...")
    mismatch_rows = compare_csvs(
        atera_csv=settings.atera_output,
        bd_csv=settings.bd_output,
        output=settings.report_output,
        duplicates_output=settings.duplicates_output,
        company_aliases=settings.company_aliases,
        device_aliases=settings.device_aliases,
        exclude_company=settings.exclude_company,
    )
    emit_status(status, f"Wrote {mismatch_rows} mismatch row(s) to {settings.report_output}")
    emit_status(status, f"Wrote duplicate entry details to {settings.duplicates_output}")

    return PipelineResult(
        atera_rows=atera_rows,
        bd_rows=bd_rows,
        mismatch_rows=mismatch_rows,
        atera_output=settings.atera_output,
        bd_output=settings.bd_output,
        report_output=settings.report_output,
        duplicates_output=settings.duplicates_output,
    )


__all__ = [
    "DEFAULT_ATERA_OUTPUT_PATH",
    "DEFAULT_ATERA_PAGE_SIZE",
    "DEFAULT_BD_API_URL",
    "DEFAULT_BD_OUTPUT_PATH",
    "DEFAULT_BD_PAGE_SIZE",
    "DEFAULT_COMPANY_ALIASES_PATH",
    "DEFAULT_COMPARE_OUTPUT_PATH",
    "DEFAULT_DEVICE_ALIASES_PATH",
    "DEFAULT_DUPLICATES_OUTPUT_PATH",
    "DEFAULT_EXCLUDE_COMPANY_PATH",
    "PipelineResult",
    "PipelineSettings",
    "bd_provider_from_settings",
    "run_pipeline",
]
