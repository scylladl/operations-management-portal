/*
    Step 01: schemas, reference data and the read-only links to NorthGridOps.

    $(SourceDatabase) is replaced by deploy.ps1 (default NorthGridOps). The portal never writes there:
    the ng synonyms are only read.
*/
IF SCHEMA_ID(N'ref')   IS NULL EXEC (N'CREATE SCHEMA ref');
IF SCHEMA_ID(N'ng')    IS NULL EXEC (N'CREATE SCHEMA ng');
IF SCHEMA_ID(N'app')   IS NULL EXEC (N'CREATE SCHEMA app');
IF SCHEMA_ID(N'audit') IS NULL EXEC (N'CREATE SCHEMA audit');
IF SCHEMA_ID(N'rpt')   IS NULL EXEC (N'CREATE SCHEMA rpt');
IF SCHEMA_ID(N'pub')   IS NULL EXEC (N'CREATE SCHEMA pub');
GO

DROP SYNONYM IF EXISTS ng.Circuit;
DROP SYNONYM IF EXISTS ng.Customer;
DROP SYNONYM IF EXISTS ng.Incident;
DROP SYNONYM IF EXISTS ng.Region;
DROP SYNONYM IF EXISTS ng.ActionType;
DROP SYNONYM IF EXISTS ng.ImprovementAction;
CREATE SYNONYM ng.Circuit           FOR [$(SourceDatabase)].ops.Circuit;
CREATE SYNONYM ng.Customer          FOR [$(SourceDatabase)].ops.Customer;
CREATE SYNONYM ng.Incident          FOR [$(SourceDatabase)].ops.Incident;
CREATE SYNONYM ng.Region            FOR [$(SourceDatabase)].ref.Region;
CREATE SYNONYM ng.ActionType        FOR [$(SourceDatabase)].ref.ActionType;
CREATE SYNONYM ng.ImprovementAction FOR [$(SourceDatabase)].ops.ImprovementAction;   -- history import and export check only
GO

IF OBJECT_ID(N'ref.Role') IS NULL
CREATE TABLE ref.Role (
    RoleCode  char(3)      NOT NULL CONSTRAINT PK_Role PRIMARY KEY,
    RoleName  nvarchar(40) NOT NULL
);

IF OBJECT_ID(N'ref.Status') IS NULL
CREATE TABLE ref.Status (
    StatusCode  varchar(12)  NOT NULL CONSTRAINT PK_Status PRIMARY KEY,
    StatusName  nvarchar(30) NOT NULL,
    SortOrder   tinyint      NOT NULL,
    IsOpen      bit          NOT NULL    -- R1: open = not Rejected, Verified or Cancelled
);

-- One row per transition and role allowed to make it. app.fn_AllowedTransitions reads this table for both the
-- buttons the app shows and the check app.usp_Transition makes, so the two cannot disagree.
IF OBJECT_ID(N'ref.Transition') IS NULL
CREATE TABLE ref.Transition (
    TransitionCode  varchar(10)  NOT NULL,
    FromStatus      varchar(12)  NOT NULL CONSTRAINT FK_Transition_From REFERENCES ref.Status,
    RoleCode        char(3)      NOT NULL CONSTRAINT FK_Transition_Role REFERENCES ref.Role,
    ToStatus        varchar(12)  NOT NULL CONSTRAINT FK_Transition_To REFERENCES ref.Status,
    ActionLabel     nvarchar(30) NOT NULL,
    RequiresReason  bit          NOT NULL,
    MustBeOwner     bit          NOT NULL,   -- only the requester (submit, resubmit)
    MustNotBeOwner  bit          NOT NULL,   -- R3: nobody decides on or verifies their own request
    CONSTRAINT PK_Transition PRIMARY KEY (TransitionCode, FromStatus, RoleCode)
);

-- Demo switches. DemoClock lets the seed script and the tests set the time the procedures record;
-- deploy.ps1 leaves it off.
IF OBJECT_ID(N'app.Setting') IS NULL
CREATE TABLE app.Setting (
    SettingCode   varchar(30) NOT NULL CONSTRAINT PK_Setting PRIMARY KEY,
    SettingValue  int         NOT NULL
);
GO

MERGE ref.Role AS t
USING (VALUES ('REQ', N'Requester'), ('APR', N'Approver'), ('FLD', N'Field coordinator'), ('ADM', N'Administrator'))
      AS s (RoleCode, RoleName)
ON t.RoleCode = s.RoleCode
WHEN MATCHED AND t.RoleName <> s.RoleName THEN UPDATE SET RoleName = s.RoleName
WHEN NOT MATCHED THEN INSERT (RoleCode, RoleName) VALUES (s.RoleCode, s.RoleName);

MERGE ref.Status AS t
USING (VALUES ('Draft',      N'Draft',       1, 1),
              ('Submitted',  N'Submitted',   2, 1),
              ('Returned',   N'Returned',    3, 1),
              ('Approved',   N'Approved',    4, 1),
              ('InProgress', N'In progress', 5, 1),
              ('Completed',  N'Completed',   6, 1),
              ('Verified',   N'Verified',    7, 0),
              ('Rejected',   N'Rejected',    8, 0),
              ('Cancelled',  N'Cancelled',   9, 0))
      AS s (StatusCode, StatusName, SortOrder, IsOpen)
ON t.StatusCode = s.StatusCode
WHEN MATCHED AND (t.StatusName <> s.StatusName OR t.SortOrder <> s.SortOrder OR t.IsOpen <> s.IsOpen)
    THEN UPDATE SET StatusName = s.StatusName, SortOrder = s.SortOrder, IsOpen = s.IsOpen
WHEN NOT MATCHED THEN INSERT (StatusCode, StatusName, SortOrder, IsOpen)
    VALUES (s.StatusCode, s.StatusName, s.SortOrder, s.IsOpen);

-- The workflow of docs/01-business-requirements.md, section 5. Administrators may do whatever approvers do.
MERGE ref.Transition AS t
USING (VALUES
    ('SUBMIT',   'Draft',      'REQ', 'Submitted',  N'Submit',            0, 1, 0),
    ('SUBMIT',   'Draft',      'APR', 'Submitted',  N'Submit',            0, 1, 0),
    ('SUBMIT',   'Draft',      'ADM', 'Submitted',  N'Submit',            0, 1, 0),
    ('RESUBMIT', 'Returned',   'REQ', 'Submitted',  N'Resubmit',          0, 1, 0),
    ('RESUBMIT', 'Returned',   'APR', 'Submitted',  N'Resubmit',          0, 1, 0),
    ('RESUBMIT', 'Returned',   'ADM', 'Submitted',  N'Resubmit',          0, 1, 0),
    ('APPROVE',  'Submitted',  'APR', 'Approved',   N'Approve',           0, 0, 1),
    ('APPROVE',  'Submitted',  'ADM', 'Approved',   N'Approve',           0, 0, 1),
    ('RETURN',   'Submitted',  'APR', 'Returned',   N'Return for changes', 1, 0, 1),
    ('RETURN',   'Submitted',  'ADM', 'Returned',   N'Return for changes', 1, 0, 1),
    ('REJECT',   'Submitted',  'APR', 'Rejected',   N'Reject',            1, 0, 1),
    ('REJECT',   'Submitted',  'ADM', 'Rejected',   N'Reject',            1, 0, 1),
    ('START',    'Approved',   'FLD', 'InProgress', N'Start work',        0, 0, 0),
    ('COMPLETE', 'InProgress', 'FLD', 'Completed',  N'Record completion', 0, 0, 0),
    ('VERIFY',   'Completed',  'APR', 'Verified',   N'Verify',            0, 0, 1),
    ('VERIFY',   'Completed',  'ADM', 'Verified',   N'Verify',            0, 0, 1),
    ('REOPEN',   'Completed',  'APR', 'InProgress', N'Reopen',            1, 0, 0),
    ('REOPEN',   'Completed',  'ADM', 'InProgress', N'Reopen',            1, 0, 0),
    ('CANCEL',   'Approved',   'APR', 'Cancelled',  N'Cancel',            1, 0, 0),
    ('CANCEL',   'Approved',   'ADM', 'Cancelled',  N'Cancel',            1, 0, 0),
    ('CANCEL',   'InProgress', 'APR', 'Cancelled',  N'Cancel',            1, 0, 0),
    ('CANCEL',   'InProgress', 'ADM', 'Cancelled',  N'Cancel',            1, 0, 0))
    AS s (TransitionCode, FromStatus, RoleCode, ToStatus, ActionLabel, RequiresReason, MustBeOwner, MustNotBeOwner)
ON t.TransitionCode = s.TransitionCode AND t.FromStatus = s.FromStatus AND t.RoleCode = s.RoleCode
WHEN MATCHED THEN UPDATE SET ToStatus = s.ToStatus, ActionLabel = s.ActionLabel, RequiresReason = s.RequiresReason,
                             MustBeOwner = s.MustBeOwner, MustNotBeOwner = s.MustNotBeOwner
WHEN NOT MATCHED BY TARGET THEN
    INSERT (TransitionCode, FromStatus, RoleCode, ToStatus, ActionLabel, RequiresReason, MustBeOwner, MustNotBeOwner)
    VALUES (s.TransitionCode, s.FromStatus, s.RoleCode, s.ToStatus, s.ActionLabel, s.RequiresReason, s.MustBeOwner, s.MustNotBeOwner)
WHEN NOT MATCHED BY SOURCE THEN DELETE;

MERGE app.Setting AS t
USING (VALUES ('DemoClock', 0)) AS s (SettingCode, SettingValue)
ON t.SettingCode = s.SettingCode
WHEN MATCHED THEN UPDATE SET SettingValue = s.SettingValue
WHEN NOT MATCHED THEN INSERT (SettingCode, SettingValue) VALUES (s.SettingCode, s.SettingValue);
GO
