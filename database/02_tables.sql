/*
    Step 02: accounts, actions and the audit trail.

    Audit (R9). Triggers on app.UserAccount, app.Action and app.ActionIncident write one audit row per changed
    field, in the transaction of the change. They take the actor, the event and the reason from SESSION_CONTEXT,
    which every app procedure sets; a change made without that context (a manual UPDATE) is refused, so no change
    can reach these tables unaudited. The audit tables refuse UPDATE and DELETE from anyone.
*/
IF OBJECT_ID(N'app.UserAccount') IS NULL
CREATE TABLE app.UserAccount (
    UserId        int           NOT NULL IDENTITY CONSTRAINT PK_UserAccount PRIMARY KEY,
    Login         varchar(50)   NOT NULL CONSTRAINT UQ_UserAccount_Login UNIQUE,
    DisplayName   nvarchar(100) NOT NULL,
    RoleCode      char(3)       NULL CONSTRAINT FK_UserAccount_Role REFERENCES ref.Role,   -- NULL while a sign-up waits
    RegionCode    char(3)       NULL,                                                    -- NULL for administrators
    PasswordHash  varchar(200)  NOT NULL,                                                -- Argon2id, encoded by argon2-cffi
    IsActive      bit           NOT NULL,
    CreatedAt     datetime2(0)  NOT NULL,
    RowVer        rowversion,
    CONSTRAINT CK_UserAccount_RoleRegion CHECK (
        (RoleCode IS NULL AND IsActive = 0)
        OR (RoleCode = 'ADM' AND RegionCode IS NULL)
        OR (RoleCode IN ('REQ', 'APR', 'FLD') AND RegionCode IS NOT NULL))
);

IF OBJECT_ID(N'app.Action') IS NULL
CREATE TABLE app.Action (
    ActionId         int            NOT NULL IDENTITY(10001, 1) CONSTRAINT PK_Action PRIMARY KEY,
    CircuitId        varchar(20)    NOT NULL,
    ActionTypeCode   varchar(15)    NOT NULL,
    RegionCode       char(3)        NULL,       -- copied from the circuit when the request is created
    Status           varchar(12)    NOT NULL CONSTRAINT FK_Action_Status REFERENCES ref.Status,
    RequesterId      int            NULL CONSTRAINT FK_Action_Requester REFERENCES app.UserAccount,
    Justification    nvarchar(2000) NULL,
    ExpectedOutcome  nvarchar(1000) NULL,
    StartDate        date           NULL,
    CompletionDate   date           NULL,
    LastSubmittedAt  datetime2(0)   NULL,       -- age in the decision queue (Q4)
    VersionNo        int            NOT NULL CONSTRAINT DF_Action_VersionNo DEFAULT 0,
    IsHistorical     bit            NOT NULL CONSTRAINT DF_Action_IsHistorical DEFAULT 0,
    RowVer           rowversion,
    -- R1: open actions share slot 0, so a second open action of the same type on a circuit breaks the unique index.
    -- A historical Completed action is finished work (history has no verification step), so it does not block.
    OpenSlot AS CASE WHEN Status IN ('Draft', 'Submitted', 'Returned', 'Approved', 'InProgress')
                       OR (Status = 'Completed' AND IsHistorical = 0) THEN 0 ELSE ActionId END PERSISTED,
    CONSTRAINT CK_Action_Region CHECK (RegionCode IS NOT NULL OR IsHistorical = 1),
    CONSTRAINT CK_Action_Requester CHECK (RequesterId IS NOT NULL OR IsHistorical = 1),
    CONSTRAINT CK_Action_Dates CHECK (CompletionDate >= StartDate)
);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UX_Action_OpenPerCircuitType')
    CREATE UNIQUE INDEX UX_Action_OpenPerCircuitType ON app.Action (CircuitId, ActionTypeCode, OpenSlot);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Action_RegionStatus')
    CREATE INDEX IX_Action_RegionStatus ON app.Action (RegionCode, Status);

-- Incidents a request addresses (R2), as currently edited
IF OBJECT_ID(N'app.ActionIncident') IS NULL
CREATE TABLE app.ActionIncident (
    ActionId  int         NOT NULL CONSTRAINT FK_ActionIncident_Action REFERENCES app.Action ON DELETE CASCADE,
    TicketId  varchar(20) NOT NULL,
    CONSTRAINT PK_ActionIncident PRIMARY KEY (ActionId, TicketId)
);

-- R5: a snapshot of each submitted version
IF OBJECT_ID(N'app.ActionVersion') IS NULL
CREATE TABLE app.ActionVersion (
    ActionId         int            NOT NULL CONSTRAINT FK_ActionVersion_Action REFERENCES app.Action,
    VersionNo        int            NOT NULL,
    CircuitId        varchar(20)    NOT NULL,
    ActionTypeCode   varchar(15)    NOT NULL,
    Justification    nvarchar(2000) NOT NULL,
    ExpectedOutcome  nvarchar(1000) NOT NULL,
    TicketIds        nvarchar(max)  NOT NULL,   -- JSON array, sorted
    SubmittedAt      datetime2(0)   NOT NULL,
    SubmittedBy      int            NOT NULL CONSTRAINT FK_ActionVersion_User REFERENCES app.UserAccount,
    CONSTRAINT PK_ActionVersion PRIMARY KEY (ActionId, VersionNo)
);

IF OBJECT_ID(N'app.WorkNote') IS NULL
CREATE TABLE app.WorkNote (
    WorkNoteId  int            NOT NULL IDENTITY CONSTRAINT PK_WorkNote PRIMARY KEY,
    ActionId    int            NOT NULL CONSTRAINT FK_WorkNote_Action REFERENCES app.Action,
    NoteText    nvarchar(1000) NOT NULL,
    CreatedAt   datetime2(0)   NOT NULL,
    CreatedBy   int            NOT NULL CONSTRAINT FK_WorkNote_User REFERENCES app.UserAccount
);

-- No foreign key to app.Action: a discarded draft (R7) is deleted, its audit rows stay.
IF OBJECT_ID(N'audit.ActionEvent') IS NULL
CREATE TABLE audit.ActionEvent (
    EventId      bigint         NOT NULL IDENTITY CONSTRAINT PK_ActionEvent PRIMARY KEY,
    ActionId     int            NOT NULL,
    EventAt      datetime2(0)   NOT NULL,
    ActorUserId  int            NOT NULL,
    EventType    varchar(12)    NOT NULL,   -- SAVE, a transition code, OWNER, DISCARD, IMPORT
    FieldName    varchar(20)    NOT NULL,
    OldValue     nvarchar(2000) NULL,
    NewValue     nvarchar(2000) NULL,
    Reason       nvarchar(1000) NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_ActionEvent_Action')
    CREATE INDEX IX_ActionEvent_Action ON audit.ActionEvent (ActionId, EventId);

IF OBJECT_ID(N'audit.UserEvent') IS NULL
CREATE TABLE audit.UserEvent (
    EventId      bigint        NOT NULL IDENTITY CONSTRAINT PK_UserEvent PRIMARY KEY,
    UserId       int           NOT NULL,
    EventAt      datetime2(0)  NOT NULL,
    ActorUserId  int           NULL,        -- NULL for a sign-up request and the first administrator
    EventType    varchar(12)   NOT NULL,
    FieldName    varchar(20)   NOT NULL,
    OldValue     nvarchar(200) NULL,
    NewValue     nvarchar(200) NULL,
    Reason       nvarchar(1000) NULL
);
GO

CREATE OR ALTER TRIGGER audit.trg_ActionEvent_InsertOnly ON audit.ActionEvent
INSTEAD OF UPDATE, DELETE
AS
    THROW 50020, 'The audit trail cannot be changed.', 1;
GO

CREATE OR ALTER TRIGGER audit.trg_UserEvent_InsertOnly ON audit.UserEvent
INSTEAD OF UPDATE, DELETE
AS
    THROW 50020, 'The audit trail cannot be changed.', 1;
GO

CREATE OR ALTER TRIGGER app.trg_Action_Audit ON app.Action
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

    DECLARE @Actor int = CAST(SESSION_CONTEXT(N'portal.actor') AS int),
            @Event varchar(12) = CAST(SESSION_CONTEXT(N'portal.event') AS varchar(12));
    IF @Actor IS NULL OR @Event IS NULL
        THROW 50010, 'Actions change only through the portal procedures.', 1;

    INSERT audit.ActionEvent (ActionId, EventAt, ActorUserId, EventType, FieldName, OldValue, NewValue, Reason)
    SELECT  COALESCE(i.ActionId, d.ActionId),
            CAST(SESSION_CONTEXT(N'portal.now') AS datetime2(0)),
            @Actor, @Event, f.FieldName, f.OldValue, f.NewValue,
            CAST(SESSION_CONTEXT(N'portal.reason') AS nvarchar(1000))
    FROM inserted AS i
    FULL JOIN deleted AS d ON d.ActionId = i.ActionId
    CROSS APPLY (VALUES
        ('Status',          d.Status,                                   i.Status),
        ('CircuitId',       d.CircuitId,                                i.CircuitId),
        ('ActionTypeCode',  d.ActionTypeCode,                           i.ActionTypeCode),
        ('RequesterId',     CAST(d.RequesterId AS nvarchar(20)),        CAST(i.RequesterId AS nvarchar(20))),
        ('Justification',   d.Justification,                            i.Justification),
        ('ExpectedOutcome', d.ExpectedOutcome,                          i.ExpectedOutcome),
        ('StartDate',       CONVERT(nvarchar(10), d.StartDate, 23),     CONVERT(nvarchar(10), i.StartDate, 23)),
        ('CompletionDate',  CONVERT(nvarchar(10), d.CompletionDate, 23), CONVERT(nvarchar(10), i.CompletionDate, 23))
    ) AS f (FieldName, OldValue, NewValue)
    WHERE f.OldValue IS DISTINCT FROM f.NewValue;
END;
GO

CREATE OR ALTER TRIGGER app.trg_ActionIncident_Audit ON app.ActionIncident
AFTER INSERT, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted) AND NOT EXISTS (SELECT 1 FROM deleted) RETURN;

    DECLARE @Actor int = CAST(SESSION_CONTEXT(N'portal.actor') AS int),
            @Event varchar(12) = CAST(SESSION_CONTEXT(N'portal.event') AS varchar(12));
    IF @Actor IS NULL OR @Event IS NULL
        THROW 50010, 'Actions change only through the portal procedures.', 1;

    INSERT audit.ActionEvent (ActionId, EventAt, ActorUserId, EventType, FieldName, OldValue, NewValue, Reason)
    SELECT ActionId, CAST(SESSION_CONTEXT(N'portal.now') AS datetime2(0)), @Actor, @Event, 'Incident', NULL, TicketId, NULL
    FROM inserted
    UNION ALL
    SELECT ActionId, CAST(SESSION_CONTEXT(N'portal.now') AS datetime2(0)), @Actor, @Event, 'Incident', TicketId, NULL, NULL
    FROM deleted;
END;
GO

CREATE OR ALTER TRIGGER app.trg_UserAccount_Audit ON app.UserAccount
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted) RETURN;

    DECLARE @Actor int = CAST(SESSION_CONTEXT(N'portal.actor') AS int),
            @Event varchar(12) = CAST(SESSION_CONTEXT(N'portal.event') AS varchar(12));
    IF @Event IS NULL OR (@Actor IS NULL AND @Event NOT IN ('SIGNUP', 'BOOTSTRAP'))
        THROW 50010, 'Accounts change only through the portal procedures.', 1;

    -- The hash itself is never copied into the trail, only the fact that it changed.
    INSERT audit.UserEvent (UserId, EventAt, ActorUserId, EventType, FieldName, OldValue, NewValue, Reason)
    SELECT  i.UserId, CAST(SESSION_CONTEXT(N'portal.now') AS datetime2(0)), @Actor, @Event,
            f.FieldName, f.OldValue, f.NewValue, CAST(SESSION_CONTEXT(N'portal.reason') AS nvarchar(1000))
    FROM inserted AS i
    LEFT JOIN deleted AS d ON d.UserId = i.UserId
    CROSS APPLY (VALUES
        ('Login',       d.Login,                             i.Login),
        ('DisplayName', d.DisplayName,                       i.DisplayName),
        ('RoleCode',    d.RoleCode,                          i.RoleCode),
        ('RegionCode',  d.RegionCode,                        i.RegionCode),
        ('IsActive',    CAST(d.IsActive AS nvarchar(1)),     CAST(i.IsActive AS nvarchar(1))),
        ('Password',    NULL, CASE WHEN d.UserId IS NULL THEN N'set'
                                   WHEN d.PasswordHash <> i.PasswordHash THEN N'changed' END)
    ) AS f (FieldName, OldValue, NewValue)
    WHERE f.OldValue IS DISTINCT FROM f.NewValue;
END;
GO
