from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nano_offline.core.database import Database
from nano_offline.repositories.definitions_repository import DefinitionsRepository
from nano_offline.repositories.item_repository import ItemRepository
from nano_offline.repositories.party_repository import PartyRepository
from nano_offline.services.auth_service import AuthService
from nano_offline.services.backup_service import BackupService
from nano_offline.services.dashboard_service import DashboardService
from nano_offline.services.document_service import DocumentService
from nano_offline.services.expense_service import ExpenseService
from nano_offline.services.invoice_service import InvoiceService
from nano_offline.services.license_service import LicenseService
from nano_offline.services.payment_service import PaymentService
from nano_offline.services.reporting_service import ReportingService
from nano_offline.services.statement_service import StatementService


@dataclass(slots=True)
class AppContext:
    db: Database
    customers: PartyRepository
    suppliers: PartyRepository
    definitions: DefinitionsRepository
    items: ItemRepository
    invoices: InvoiceService
    payments: PaymentService
    expenses: ExpenseService
    statements: StatementService
    reports: ReportingService
    dashboard: DashboardService
    documents: DocumentService
    auth: AuthService
    backup: BackupService
    license: LicenseService

    @classmethod
    def create(cls, db_path: str | Path) -> "AppContext":
        db = Database(db_path)
        db.initialize()
        invoices = InvoiceService(db)
        expenses = ExpenseService(db)
        # Required after phase-2 -> phase-3 migration: initial invoice payments
        # become explicit payment/allocation rows and all balances are reconciled.
        invoices.rebuild_derived_state()
        expenses.rebuild_ledger()
        auth = AuthService(db)
        backup = BackupService(db)
        return cls(
            db=db,
            customers=PartyRepository(db, "customers"),
            suppliers=PartyRepository(db, "suppliers"),
            definitions=DefinitionsRepository(db),
            items=ItemRepository(db),
            invoices=invoices,
            payments=PaymentService(db),
            expenses=expenses,
            statements=StatementService(db),
            reports=ReportingService(db),
            dashboard=DashboardService(db),
            documents=DocumentService(db, invoices, StatementService(db)),
            auth=auth,
            backup=backup,
            license=LicenseService(db),
        )
