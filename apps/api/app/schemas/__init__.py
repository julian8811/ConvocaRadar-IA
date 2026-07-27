"""Re-export facade for backward-compatible ``from app.schemas import X`` imports.

All domain schemas are defined in their respective module files and re-exported
here so existing import paths continue to work. This facade can be removed in a
future cleanup once all callers import from the domain modules directly.
"""

# ── auth ──
from app.schemas.auth import (  # noqa: F401
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    Token,
    UserRead,
)

# ── org ──
from app.schemas.org import (  # noqa: F401
    OrganizationProfileRead,
    OrganizationProfileUpsert,
    OrganizationRead,
    OrganizationUpdate,
)

# ── source ──
from app.schemas.source import (  # noqa: F401
    ConnectorProbeRequest,
    SourceBase,
    SourceCreate,
    SourceHealthRead,
    SourceRead,
    SourceRunCandidate,
    SourceRunComplete,
    SourceRunOverviewRead,
    SourceRunRead,
    SourceUpdate,
)

# ── opportunity ──
from app.schemas.opportunity import (  # noqa: F401
    OpportunityCreate,
    OpportunityDocumentRead,
    OpportunityList,
    OpportunityRead,
    OpportunitySemanticList,
    OpportunitySemanticMatch,
    OpportunityUpdate,
    ScoreRead,
)

# ── dashboard ──
from app.schemas.dashboard import (  # noqa: F401
    AdminMetricsRead,
    DashboardBreakdownItem,
    DashboardDataCoverage,
    DashboardOpportunityItem,
    DashboardProfileSummary,
    DashboardSourceAlert,
    DashboardSummaryRead,
    HealthKpis,
    HealthRead,
    PipelineOpportunityItem,
    PipelineRead,
    TriageOpportunityItem,
    TriageRead,
)

# ── alerts ──
from app.schemas.alerts import (  # noqa: F401
    AlertCreate,
    AlertRead,
    AlertTestRequest,
    AlertUpdate,
    AuditLogRead,
)

# ── ai ──
from app.schemas.ai import (  # noqa: F401
    AiOpportunityExtract,
    AiTextRequest,
)

# ── report ──
from app.schemas.report import (  # noqa: F401
    ReportCreate,
    ReportRead,
    TaskRead,
)
