from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nano_offline.core.database import Database
from nano_offline.repositories.definitions_repository import DefinitionsRepository
from nano_offline.repositories.item_repository import ItemRepository
from nano_offline.repositories.party_repository import PartyRepository
from nano_offline.repositories.settings_repository import SettingsRepository
from nano_offline.repositories.stocktake_repository import StocktakeRepository
from nano_offline.services.auth_service import AuthService
from nano_offline.services.backup_service import BackupService
from nano_offline.services.dashboard_service import DashboardService
from nano_offline.services.document_service import DocumentService
from nano_offline.services.expense_service import ExpenseService
from nano_offline.services.forecast_service import ForecastService
from nano_offline.services.invoice_service import InvoiceService
from nano_offline.services.license_service import LicenseService
from nano_offline.services.external_notifications import ExternalNotificationService
from nano_offline.services.notification_service import NotificationService
from nano_offline.services.payment_service import PaymentService
from nano_offline.services.reporting_service import ReportingService
from nano_offline.services.statement_service import StatementService
from nano_offline.services.stocktake_service import StocktakeService
from nano_offline.services.smart_assistant_service import SmartAssistantService
from nano_offline.services.cash_day_close_service import CashDayCloseService
from nano_offline.services.owner_pulse_service import OwnerPulseService
from nano_offline.services.crisis_mode_service import CrisisModeService
from nano_offline.services.party_trust_service import PartyTrustService
from nano_offline.services.business_memory_service import BusinessMemoryService
from nano_offline.services.quick_command_service import QuickCommandService


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
    forecast: ForecastService
    dashboard: DashboardService
    documents: DocumentService
    settings: SettingsRepository
    auth: AuthService
    backup: BackupService
    license: LicenseService
    notifications: NotificationService
    external_notifications: ExternalNotificationService
    smart_assistant: SmartAssistantService
    cash_day_close: CashDayCloseService
    stocktake: StocktakeService
    owner_pulse: OwnerPulseService
    crisis_mode: CrisisModeService
    party_trust: PartyTrustService
    business_memory: BusinessMemoryService
    quick_commands: QuickCommandService

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
        items_repo = ItemRepository(db)
        stocktake_repo = StocktakeRepository(db)
        settings_repo = SettingsRepository(db)
        dashboard_svc = DashboardService(db)
        license_svc = LicenseService(db)
        notifications_svc = NotificationService(
            db, settings_repo, items_repo, ReportingService(db), license_svc, dashboard_svc
        )
        external_notifications_svc = ExternalNotificationService(db, settings_repo, notifications_svc)
        # PHASE11.1: wire the immediate-push hook -- the moment the rules
        # engine creates a NEW alert, fan it out through the enabled external
        # channels right away (same rules, same quiet hours, delivery-log
        # dedupe) instead of waiting for the next app launch. Fire-and-forget
        # via a daemon thread inside the external service.
        notifications_svc.set_external_hook(external_notifications_svc.background_dispatch)
        business_memory_svc = BusinessMemoryService(db, settings=settings_repo)
        smart_assistant_svc = SmartAssistantService(
            db,
            notifications=notifications_svc,
            dashboard=dashboard_svc,
            settings=settings_repo,
            business_memory=business_memory_svc,
        )
        crisis_mode_svc = CrisisModeService(
            db,
            settings=settings_repo,
            items=items_repo,
        )
        party_trust_svc = PartyTrustService(db)
        quick_commands_svc = QuickCommandService(db, items=items_repo)
        owner_pulse_svc = OwnerPulseService(
            db,
            dashboard=dashboard_svc,
            smart_assistant=smart_assistant_svc,
            settings=settings_repo,
            business_memory=business_memory_svc,
        )
        return cls(
            db=db,
            customers=PartyRepository(db, "customers"),
            suppliers=PartyRepository(db, "suppliers"),
            definitions=DefinitionsRepository(db),
            items=items_repo,
            invoices=invoices,
            payments=PaymentService(db),
            expenses=expenses,
            statements=StatementService(db),
            reports=ReportingService(db),
            forecast=ForecastService(db),
            dashboard=dashboard_svc,
            documents=DocumentService(db, invoices, StatementService(db)),
            settings=settings_repo,
            auth=auth,
            backup=backup,
            license=license_svc,
            notifications=notifications_svc,
            external_notifications=external_notifications_svc,
            smart_assistant=smart_assistant_svc,
            cash_day_close=CashDayCloseService(db),
            stocktake=StocktakeService(db, items_repo, stocktake_repo, auth),
            owner_pulse=owner_pulse_svc,
            crisis_mode=crisis_mode_svc,
            party_trust=party_trust_svc,
            business_memory=business_memory_svc,
            quick_commands=quick_commands_svc,
        )

    def reload(self, db_path: str | Path) -> None:
        """Rebuild every repository/service against a freshly-opened ``Database``.

        ``Database.connect()`` already opens a new sqlite3 connection by path
        on every call, so a plain file swap on disk (as ``restore_backup``
        does) is in principle picked up by future queries automatically.
        The real problem after a restore is everything *above* the database
        layer: every open view already holds Python objects it fetched
        before the restore, and several services build derived/reconciled
        state once at construction time (see ``invoices.rebuild_derived_state``
        and ``expenses.rebuild_ledger`` in ``create()`` above) rather than
        recomputing it per-query. Restoring the file alone leaves that
        derived state stale.

        This mutates ``self`` in place (the dataclass is not frozen) instead
        of building a new ``AppContext``, so every view/service that already
        holds a reference to this same object -- ``self.ctx`` in every
        ``*_view.py`` -- transparently starts hitting the restored database
        the next time it queries, with no need to re-thread a new context
        object through the whole call graph. Callers are still expected to
        force the user back to the login screen right after this (see
        ``AdminCenter``'s restore flow) so every view is rebuilt from scratch
        against the restored data instead of showing stale, already-rendered
        rows from before the restore.
        """
        fresh = AppContext.create(db_path)
        for field_name in self.__dataclass_fields__:
            setattr(self, field_name, getattr(fresh, field_name))
