/*
    Step 04: the commands and queries the app calls on actions.

    Every command runs in one transaction with XACT_ABORT, so a failure anywhere (the audit trigger included)
    leaves nothing behind (AC-03). It locks the action, refuses it if its RowVer is not the one the user saw
    (R12), then checks the rules. Errors the user can act on use these numbers, mapped in portal/db.py:
        50001 not allowed   50002 invalid input   50003 changed meanwhile   50004 not found   50005 duplicate
*/
CREATE OR ALTER PROCEDURE app.usp_SaveRequest
    @ActorUserId      int,
    @ActionId         int            = NULL,   -- NULL creates a draft
    @RowVer           binary(8)      = NULL,
    @CircuitId        varchar(20)    = NULL,   -- on an existing request, NULL keeps the current value
    @ActionTypeCode   varchar(15)    = NULL,
    @Justification    nvarchar(2000) = NULL,
    @ExpectedOutcome  nvarchar(1000) = NULL,
    @TicketIds        nvarchar(max)  = NULL    -- JSON array of ticket ids
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @Now datetime2(0) = app.fn_Now(), @Message nvarchar(400);
    EXEC app.usp_SetContext @ActorUserId, 'SAVE', NULL, @Now;

    BEGIN TRY
        DECLARE @Role char(3), @ActorRegion char(3);
        SELECT @Role = RoleCode, @ActorRegion = RegionCode
        FROM app.UserAccount WHERE UserId = @ActorUserId AND IsActive = 1;
        IF @Role IS NULL OR @Role NOT IN ('REQ', 'APR', 'ADM')
            THROW 50001, 'Only requesters, approvers and administrators can request actions.', 1;

        DECLARE @Tickets TABLE (TicketId varchar(20) PRIMARY KEY);
        IF @TicketIds IS NOT NULL
            INSERT @Tickets SELECT DISTINCT value FROM OPENJSON(@TicketIds);

        BEGIN TRANSACTION;

        IF @ActionId IS NOT NULL
        BEGIN
            DECLARE @Status varchar(12), @Owner int, @CurrentRowVer binary(8);
            SELECT @Status = Status, @Owner = RequesterId, @CurrentRowVer = RowVer,
                   @CircuitId = COALESCE(@CircuitId, CircuitId),
                   @ActionTypeCode = COALESCE(@ActionTypeCode, ActionTypeCode),
                   @Justification = COALESCE(@Justification, Justification),
                   @ExpectedOutcome = COALESCE(@ExpectedOutcome, ExpectedOutcome)
            FROM app.Action WITH (UPDLOCK, HOLDLOCK) WHERE ActionId = @ActionId;
            IF @Status IS NULL OR @Owner IS DISTINCT FROM @ActorUserId
                THROW 50001, 'Only the requester can edit a request.', 1;
            IF @CurrentRowVer <> @RowVer
                THROW 50003, 'This request changed since you opened it. Reload it to see the current version.', 1;
            IF @Status NOT IN ('Draft', 'Returned')
                THROW 50001, 'A request can be edited only as a draft or after it was returned.', 1;
            IF @TicketIds IS NULL
                INSERT @Tickets SELECT TicketId FROM app.ActionIncident WHERE ActionId = @ActionId;
        END;

        -- R13: the circuit must be in the inventory, with a region, and not decommissioned
        DECLARE @CircuitRegion char(3), @Decommissioned date, @CircuitFound bit = 0;
        SELECT @CircuitRegion = RegionCode, @Decommissioned = DecommissionDate, @CircuitFound = 1
        FROM ng.Circuit WHERE CircuitId = @CircuitId;
        IF @CircuitFound = 0
            THROW 50002, 'This circuit is not in the NorthGrid inventory.', 1;
        IF @CircuitRegion IS NULL
            THROW 50002, 'This circuit has no region in the inventory, so no approver can decide on it. Ask the inventory team to complete it.', 1;
        IF @Decommissioned IS NOT NULL
        BEGIN
            SET @Message = CONCAT(N'This circuit was decommissioned on ', CONVERT(nvarchar(10), @Decommissioned, 23), N'.');
            THROW 50002, @Message, 1;
        END;
        IF @Role <> 'ADM' AND @CircuitRegion <> @ActorRegion
            THROW 50001, 'You can request actions only for circuits of your region.', 1;
        IF NOT EXISTS (SELECT 1 FROM ng.ActionType WHERE ActionTypeCode = @ActionTypeCode)
            THROW 50002, 'Unknown action type.', 1;

        -- R2: only incidents of this circuit inside the evidence window
        DECLARE @BadTicket varchar(20) = (
            SELECT TOP (1) t.TicketId FROM @Tickets AS t
            WHERE NOT EXISTS (SELECT 1 FROM app.vw_EvidenceIncident AS e
                              WHERE e.TicketId = t.TicketId AND e.CircuitId = @CircuitId)
            ORDER BY t.TicketId);
        IF @BadTicket IS NOT NULL
        BEGIN
            SET @Message = CONCAT(N'Incident ', @BadTicket, N' is not an incident of circuit ', @CircuitId,
                                  N' in the evidence window.');
            THROW 50002, @Message, 1;
        END;

        IF @ActionId IS NULL
        BEGIN
            INSERT app.Action (CircuitId, ActionTypeCode, RegionCode, Status, RequesterId, Justification, ExpectedOutcome)
            VALUES (@CircuitId, @ActionTypeCode, @CircuitRegion, 'Draft', @ActorUserId,
                    NULLIF(TRIM(@Justification), N''), NULLIF(TRIM(@ExpectedOutcome), N''));
            SET @ActionId = SCOPE_IDENTITY();
        END
        ELSE
            UPDATE app.Action
            SET CircuitId = @CircuitId, ActionTypeCode = @ActionTypeCode, RegionCode = @CircuitRegion,
                Justification = NULLIF(TRIM(@Justification), N''), ExpectedOutcome = NULLIF(TRIM(@ExpectedOutcome), N'')
            WHERE ActionId = @ActionId;

        DELETE FROM app.ActionIncident
        WHERE ActionId = @ActionId AND TicketId NOT IN (SELECT TicketId FROM @Tickets);
        INSERT app.ActionIncident (ActionId, TicketId)
        SELECT @ActionId, t.TicketId FROM @Tickets AS t
        WHERE NOT EXISTS (SELECT 1 FROM app.ActionIncident AS i WHERE i.ActionId = @ActionId AND i.TicketId = t.TicketId);

        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        EXEC app.usp_ClearContext;
        IF ERROR_NUMBER() IN (2601, 2627) AND ERROR_MESSAGE() LIKE N'%UX_Action_OpenPerCircuitType%'
        BEGIN
            SELECT TOP (1) @Message = CONCAT(N'Circuit ', @CircuitId, N' already has an open action of this type (action ',
                                             ActionId, N', ', Status, N').')
            FROM app.Action
            WHERE CircuitId = @CircuitId AND ActionTypeCode = @ActionTypeCode AND OpenSlot = 0;
            THROW 50005, @Message, 1;
        END;
        THROW;
    END CATCH;

    EXEC app.usp_ClearContext;
    SELECT ActionId, RowVer FROM app.Action WHERE ActionId = @ActionId;
END;
GO

CREATE OR ALTER PROCEDURE app.usp_Transition
    @ActorUserId     int,
    @ActionId        int,
    @RowVer          binary(8),
    @TransitionCode  varchar(10),
    @Reason          nvarchar(1000) = NULL,
    @EventDate       date           = NULL   -- start date (START) or completion date (COMPLETE)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @Now datetime2(0) = app.fn_Now(), @Message nvarchar(400);
    SET @Reason = NULLIF(TRIM(@Reason), N'');
    EXEC app.usp_SetContext @ActorUserId, @TransitionCode, @Reason, @Now;

    BEGIN TRY
        BEGIN TRANSACTION;

        DECLARE @Status varchar(12), @CurrentRowVer binary(8), @StartDate date, @CircuitId varchar(20),
                @Justification nvarchar(2000), @ExpectedOutcome nvarchar(1000);
        SELECT @Status = Status, @CurrentRowVer = RowVer, @StartDate = StartDate, @CircuitId = CircuitId,
               @Justification = Justification, @ExpectedOutcome = ExpectedOutcome
        FROM app.Action WITH (UPDLOCK, HOLDLOCK) WHERE ActionId = @ActionId;
        IF @Status IS NULL
            THROW 50004, 'This action does not exist.', 1;
        IF @CurrentRowVer <> @RowVer
            THROW 50003, 'This action changed since you opened it. Reload it to see its current state.', 1;

        DECLARE @ToStatus varchar(12), @RequiresReason bit;
        SELECT @ToStatus = ToStatus, @RequiresReason = RequiresReason
        FROM app.fn_AllowedTransitions(@ActorUserId, @ActionId)
        WHERE TransitionCode = @TransitionCode;
        IF @ToStatus IS NULL
            THROW 50001, 'You cannot do this on this action.', 1;
        IF @RequiresReason = 1 AND @Reason IS NULL
            THROW 50002, 'Write the reason; the requester and the audit trail need it.', 1;

        DECLARE @Today date = CAST(@Now AS date);
        IF @TransitionCode IN ('SUBMIT', 'RESUBMIT')
        BEGIN
            IF @Justification IS NULL OR @ExpectedOutcome IS NULL
                THROW 50002, 'A request needs a justification and an expected outcome.', 1;
            IF NOT EXISTS (SELECT 1 FROM app.ActionIncident WHERE ActionId = @ActionId)
                THROW 50002, 'Link at least one incident of the last 90 days that this action addresses.', 1;
            -- A newer extraction may have moved the window since the draft was saved
            DECLARE @Stale varchar(20) = (
                SELECT TOP (1) i.TicketId FROM app.ActionIncident AS i
                WHERE i.ActionId = @ActionId
                  AND NOT EXISTS (SELECT 1 FROM app.vw_EvidenceIncident AS e
                                  WHERE e.TicketId = i.TicketId AND e.CircuitId = @CircuitId));
            IF @Stale IS NOT NULL
            BEGIN
                SET @Message = CONCAT(N'Incident ', @Stale, N' is no longer in the evidence window. Remove it and save again.');
                THROW 50002, @Message, 1;
            END;
        END;
        IF @TransitionCode IN ('START', 'COMPLETE') AND (@EventDate IS NULL OR @EventDate > @Today)
            THROW 50002, 'The date is required and cannot be in the future.', 1;
        IF @TransitionCode = 'COMPLETE' AND @EventDate < @StartDate
            THROW 50002, 'The completion date cannot be before the start date.', 1;

        DECLARE @IsSubmission bit = IIF(@TransitionCode IN ('SUBMIT', 'RESUBMIT'), 1, 0);
        UPDATE app.Action
        SET Status = @ToStatus,
            StartDate = IIF(@TransitionCode = 'START', @EventDate, StartDate),
            CompletionDate = CASE @TransitionCode WHEN 'COMPLETE' THEN @EventDate
                                                  WHEN 'REOPEN' THEN NULL
                                                  ELSE CompletionDate END,
            LastSubmittedAt = IIF(@IsSubmission = 1, @Now, LastSubmittedAt),
            VersionNo = VersionNo + @IsSubmission
        WHERE ActionId = @ActionId;

        IF @IsSubmission = 1
            INSERT app.ActionVersion (ActionId, VersionNo, CircuitId, ActionTypeCode, Justification, ExpectedOutcome,
                                      TicketIds, SubmittedAt, SubmittedBy)
            SELECT a.ActionId, a.VersionNo, a.CircuitId, a.ActionTypeCode, a.Justification, a.ExpectedOutcome,
                   (SELECT N'[' + STRING_AGG(N'"' + STRING_ESCAPE(TicketId, 'json') + N'"', N',')
                                  WITHIN GROUP (ORDER BY TicketId) + N']'
                    FROM app.ActionIncident WHERE ActionId = a.ActionId),
                   @Now, @ActorUserId
            FROM app.Action AS a WHERE a.ActionId = @ActionId;

        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        EXEC app.usp_ClearContext;
        THROW;
    END CATCH;

    EXEC app.usp_ClearContext;
    SELECT RowVer FROM app.Action WHERE ActionId = @ActionId;
END;
GO

-- R7: a draft can be discarded by its requester; anything submitted stays
CREATE OR ALTER PROCEDURE app.usp_DiscardDraft
    @ActorUserId int, @ActionId int, @RowVer binary(8)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @Now datetime2(0) = app.fn_Now();
    EXEC app.usp_SetContext @ActorUserId, 'DISCARD', NULL, @Now;

    BEGIN TRY
        BEGIN TRANSACTION;
        DECLARE @Status varchar(12), @Owner int, @CurrentRowVer binary(8);
        SELECT @Status = Status, @Owner = RequesterId, @CurrentRowVer = RowVer
        FROM app.Action WITH (UPDLOCK, HOLDLOCK) WHERE ActionId = @ActionId;
        IF @Status IS NULL OR @Owner IS DISTINCT FROM @ActorUserId
           OR NOT EXISTS (SELECT 1 FROM app.UserAccount WHERE UserId = @ActorUserId AND IsActive = 1)
            THROW 50001, 'Only the requester can discard a draft.', 1;
        IF @CurrentRowVer <> @RowVer
            THROW 50003, 'This draft changed since you opened it.', 1;
        IF @Status <> 'Draft'
            THROW 50001, 'A submitted request cannot be discarded; it ends as rejected, verified or cancelled.', 1;
        DELETE FROM app.Action WHERE ActionId = @ActionId;
        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        EXEC app.usp_ClearContext;
        THROW;
    END CATCH;
    EXEC app.usp_ClearContext;
END;
GO

-- R8: an administrator moves an open request to another requester of the region
CREATE OR ALTER PROCEDURE app.usp_ChangeOwner
    @ActorUserId int, @ActionId int, @RowVer binary(8), @NewOwnerId int, @Reason nvarchar(1000)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @Now datetime2(0) = app.fn_Now();
    SET @Reason = NULLIF(TRIM(@Reason), N'');
    EXEC app.usp_SetContext @ActorUserId, 'OWNER', @Reason, @Now;

    BEGIN TRY
        IF NOT EXISTS (SELECT 1 FROM app.UserAccount WHERE UserId = @ActorUserId AND IsActive = 1 AND RoleCode = 'ADM')
            THROW 50001, 'Only administrators can change the owner of a request.', 1;
        IF @Reason IS NULL
            THROW 50002, 'Write the reason for the change of owner.', 1;

        BEGIN TRANSACTION;
        DECLARE @Region char(3), @CurrentRowVer binary(8), @IsOpen bit, @Historical bit;
        SELECT @Region = a.RegionCode, @CurrentRowVer = a.RowVer, @IsOpen = s.IsOpen, @Historical = a.IsHistorical
        FROM app.Action AS a WITH (UPDLOCK, HOLDLOCK)
        JOIN ref.Status AS s ON s.StatusCode = a.Status
        WHERE a.ActionId = @ActionId;
        IF @CurrentRowVer IS NULL
            THROW 50004, 'This action does not exist.', 1;
        IF @CurrentRowVer <> @RowVer
            THROW 50003, 'This action changed since you opened it.', 1;
        IF @IsOpen = 0 OR @Historical = 1
            THROW 50002, 'Only open portal requests can change owner.', 1;
        IF NOT EXISTS (SELECT 1 FROM app.UserAccount
                       WHERE UserId = @NewOwnerId AND IsActive = 1
                         AND (RoleCode = 'ADM' OR (RoleCode IN ('REQ', 'APR') AND RegionCode = @Region)))
            THROW 50002, 'The new owner must be an active requester or approver of the action''s region.', 1;

        UPDATE app.Action SET RequesterId = @NewOwnerId WHERE ActionId = @ActionId;
        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        EXEC app.usp_ClearContext;
        THROW;
    END CATCH;
    EXEC app.usp_ClearContext;
    SELECT RowVer FROM app.Action WHERE ActionId = @ActionId;
END;
GO

-- Progress notes (field coordinators, section 4). A note is its own dated, signed record and is never edited.
CREATE OR ALTER PROCEDURE app.usp_AddWorkNote
    @ActorUserId int, @ActionId int, @NoteText nvarchar(1000)
AS
BEGIN
    SET NOCOUNT ON;
    SET @NoteText = NULLIF(TRIM(@NoteText), N'');
    IF @NoteText IS NULL
        THROW 50002, 'The note is empty.', 1;
    IF NOT EXISTS (SELECT 1
                   FROM app.Action AS a
                   JOIN app.UserAccount AS u ON u.UserId = @ActorUserId AND u.IsActive = 1 AND u.RoleCode = 'FLD'
                                            AND u.RegionCode = a.RegionCode
                   WHERE a.ActionId = @ActionId AND a.Status = 'InProgress')
        THROW 50001, 'Only a field coordinator of the region can add notes, while the work is in progress.', 1;
    INSERT app.WorkNote (ActionId, NoteText, CreatedAt, CreatedBy) VALUES (@ActionId, @NoteText, app.fn_Now(), @ActorUserId);
END;
GO

CREATE OR ALTER PROCEDURE app.usp_GetAction
    @ActorUserId int, @ActionId int
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM app.fn_VisibleActions(@ActorUserId) WHERE ActionId = @ActionId)
        THROW 50004, 'This action does not exist or is not visible to you.', 1;

    SELECT a.ActionId, a.CircuitId, cu.CustomerName, c.TechnologyCode, c.Province, a.ActionTypeCode,
           t.ActionTypeName, a.RegionCode, r.RegionName, a.Status, s.StatusName, a.RequesterId,
           u.DisplayName AS RequesterName, a.Justification, a.ExpectedOutcome, a.StartDate, a.CompletionDate,
           a.LastSubmittedAt, a.VersionNo, a.IsHistorical, a.RowVer
    FROM app.Action AS a
    JOIN ref.Status AS s ON s.StatusCode = a.Status
    JOIN ng.ActionType AS t ON t.ActionTypeCode = a.ActionTypeCode
    LEFT JOIN ng.Region AS r ON r.RegionCode = a.RegionCode
    LEFT JOIN ng.Circuit AS c ON c.CircuitId = a.CircuitId
    LEFT JOIN ng.Customer AS cu ON cu.CustomerId = c.CustomerId
    LEFT JOIN app.UserAccount AS u ON u.UserId = a.RequesterId
    WHERE a.ActionId = @ActionId;

    SELECT i.TicketId, n.OpenedAt, n.PriorityCode, n.RootCauseCode, n.ResponsibleTeam, n.Status
    FROM app.ActionIncident AS i
    LEFT JOIN ng.Incident AS n ON n.TicketId = i.TicketId
    WHERE i.ActionId = @ActionId
    ORDER BY n.OpenedAt;

    SELECT v.VersionNo, v.CircuitId, v.ActionTypeCode, v.Justification, v.ExpectedOutcome, v.TicketIds,
           v.SubmittedAt, u.DisplayName AS SubmittedBy
    FROM app.ActionVersion AS v
    JOIN app.UserAccount AS u ON u.UserId = v.SubmittedBy
    WHERE v.ActionId = @ActionId
    ORDER BY v.VersionNo DESC;

    SELECT e.EventAt, u.DisplayName AS ActorName, e.EventType, e.FieldName, e.OldValue, e.NewValue, e.Reason
    FROM audit.ActionEvent AS e
    JOIN app.UserAccount AS u ON u.UserId = e.ActorUserId
    WHERE e.ActionId = @ActionId
    ORDER BY e.EventId;

    SELECT w.NoteText, w.CreatedAt, u.DisplayName AS CreatedBy
    FROM app.WorkNote AS w
    JOIN app.UserAccount AS u ON u.UserId = w.CreatedBy
    WHERE w.ActionId = @ActionId
    ORDER BY w.WorkNoteId;

    SELECT TransitionCode, ActionLabel, ToStatus, RequiresReason
    FROM app.fn_AllowedTransitions(@ActorUserId, @ActionId)
    ORDER BY CASE TransitionCode WHEN 'APPROVE' THEN 1 WHEN 'VERIFY' THEN 1 WHEN 'SUBMIT' THEN 1 WHEN 'RESUBMIT' THEN 1
                                 WHEN 'START' THEN 1 WHEN 'COMPLETE' THEN 1 ELSE 2 END, TransitionCode;
END;
GO

CREATE OR ALTER PROCEDURE app.usp_ListActions
    @ActorUserId int, @ListName varchar(10)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Role char(3) = (SELECT RoleCode FROM app.UserAccount WHERE UserId = @ActorUserId AND IsActive = 1);
    IF @Role IS NULL
        THROW 50001, 'Your account is not active.', 1;
    IF @ListName NOT IN ('mine', 'decide', 'verify', 'work', 'region', 'all')
        THROW 50002, 'Unknown list.', 1;

    DECLARE @Today date = CAST(app.fn_Now() AS date);
    SELECT a.ActionId, a.CircuitId, a.ActionTypeCode, t.ActionTypeName, a.RegionCode, a.Status, s.StatusName,
           u.DisplayName AS RequesterName, a.LastSubmittedAt,
           IIF(a.Status = 'Submitted', wd.WorkingDays, NULL) AS WaitingWorkingDays,
           a.StartDate, a.CompletionDate, a.IsHistorical
    FROM app.Action AS a
    JOIN app.fn_VisibleActions(@ActorUserId) AS v ON v.ActionId = a.ActionId
    JOIN ref.Status AS s ON s.StatusCode = a.Status
    JOIN ng.ActionType AS t ON t.ActionTypeCode = a.ActionTypeCode
    LEFT JOIN app.UserAccount AS u ON u.UserId = a.RequesterId
    OUTER APPLY app.fn_WorkingDays(CAST(a.LastSubmittedAt AS date), @Today) AS wd
    WHERE CASE @ListName
            WHEN 'mine'   THEN IIF(a.RequesterId = @ActorUserId, 1, 0)
            WHEN 'decide' THEN IIF(a.Status = 'Submitted' AND @Role IN ('APR', 'ADM')
                                   AND a.RequesterId <> @ActorUserId, 1, 0)
            WHEN 'verify' THEN IIF(a.Status = 'Completed' AND a.IsHistorical = 0 AND @Role IN ('APR', 'ADM')
                                   AND a.RequesterId <> @ActorUserId, 1, 0)
            WHEN 'work'   THEN IIF(a.Status IN ('Approved', 'InProgress') AND @Role = 'FLD', 1, 0)
            ELSE 1
          END = 1
    ORDER BY CASE WHEN @ListName = 'decide' THEN a.LastSubmittedAt END,
             s.SortOrder, a.ActionId DESC;
END;
GO

-- Circuits that can be requested in a region (all regions when NULL). The inventory is the same for every
-- portal user, so the app may cache this.
CREATE OR ALTER PROCEDURE app.usp_ListCircuits
    @RegionCode char(3) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SELECT c.CircuitId, cu.CustomerName, c.TechnologyCode, c.Province, c.RegionCode, COUNT(e.TicketId) AS RecentIncidents
    FROM ng.Circuit AS c
    JOIN ng.Customer AS cu ON cu.CustomerId = c.CustomerId
    LEFT JOIN app.vw_EvidenceIncident AS e ON e.CircuitId = c.CircuitId
    WHERE c.RegionCode IS NOT NULL AND c.DecommissionDate IS NULL
      AND (@RegionCode IS NULL OR c.RegionCode = @RegionCode)
    GROUP BY c.CircuitId, cu.CustomerName, c.TechnologyCode, c.Province, c.RegionCode
    ORDER BY RecentIncidents DESC, c.CircuitId;
END;
GO

-- What a requester sees when picking a circuit (R2): its incidents in the window and its past actions
CREATE OR ALTER PROCEDURE app.usp_GetCircuitEvidence
    @ActorUserId int, @CircuitId varchar(20)
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM app.UserAccount WHERE UserId = @ActorUserId AND IsActive = 1)
        THROW 50001, 'Your account is not active.', 1;
    IF NOT EXISTS (SELECT 1 FROM ng.Circuit WHERE CircuitId = @CircuitId)
        THROW 50004, 'This circuit is not in the NorthGrid inventory.', 1;

    SELECT c.CircuitId, cu.CustomerName, cu.Segment, c.TechnologyCode, c.Province, c.RegionCode, r.RegionName,
           c.InstallDate, c.DecommissionDate, w.WindowStart, w.WindowEnd
    FROM ng.Circuit AS c
    JOIN ng.Customer AS cu ON cu.CustomerId = c.CustomerId
    LEFT JOIN ng.Region AS r ON r.RegionCode = c.RegionCode
    CROSS JOIN app.vw_EvidenceWindow AS w
    WHERE c.CircuitId = @CircuitId;

    SELECT TicketId, OpenedAt, PriorityCode, RootCauseCode, ResponsibleTeam, Status
    FROM app.vw_EvidenceIncident
    WHERE CircuitId = @CircuitId
    ORDER BY OpenedAt DESC;

    -- Past and current actions on the circuit, without their content (drafts are private)
    SELECT a.ActionId, t.ActionTypeName, s.StatusName, a.StartDate, a.CompletionDate, a.IsHistorical
    FROM app.Action AS a
    JOIN ref.Status AS s ON s.StatusCode = a.Status
    JOIN ng.ActionType AS t ON t.ActionTypeCode = a.ActionTypeCode
    WHERE a.CircuitId = @CircuitId AND a.Status <> 'Draft'
    ORDER BY COALESCE(a.StartDate, CAST(a.LastSubmittedAt AS date)) DESC;
END;
GO

-- Q6: one-time copy of the NorthGrid history. A setup step, not granted to the app's role.
CREATE OR ALTER PROCEDURE app.usp_ImportHistory
    @ActorUserId int
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF NOT EXISTS (SELECT 1 FROM app.UserAccount WHERE UserId = @ActorUserId AND IsActive = 1 AND RoleCode = 'ADM')
        THROW 50001, 'Only administrators can import the history.', 1;
    IF EXISTS (SELECT 1 FROM app.Action WHERE IsHistorical = 1)
        THROW 50002, 'The history is already imported.', 1;

    DECLARE @Now datetime2(0) = app.fn_Now();
    EXEC app.usp_SetContext @ActorUserId, 'IMPORT', N'NorthGrid improvement actions before the portal (Q6)', @Now;

    BEGIN TRY
        BEGIN TRANSACTION;
        SET IDENTITY_INSERT app.Action ON;
        INSERT app.Action (ActionId, CircuitId, ActionTypeCode, RegionCode, Status, StartDate, CompletionDate, IsHistorical)
        SELECT h.ActionId, h.CircuitId, h.ActionTypeCode, c.RegionCode,
               CASE h.Status WHEN 'In progress' THEN 'InProgress' ELSE h.Status END,
               h.StartDate, h.CompletionDate, 1
        FROM ng.ImprovementAction AS h
        LEFT JOIN ng.Circuit AS c ON c.CircuitId = h.CircuitId;
        DECLARE @Imported int = @@ROWCOUNT;
        SET IDENTITY_INSERT app.Action OFF;
        -- Explicit ids move the identity down to 558; portal actions keep starting at 10001
        IF IDENT_CURRENT('app.Action') < 10001
            DBCC CHECKIDENT ('app.Action', RESEED, 10000) WITH NO_INFOMSGS;
        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        EXEC app.usp_ClearContext;
        THROW;
    END CATCH;
    EXEC app.usp_ClearContext;
    SELECT @Imported AS Imported;
END;
GO

-- Action types and regions for the forms; the same for every user, so the app caches them
CREATE OR ALTER PROCEDURE app.usp_ListReference
AS
BEGIN
    SET NOCOUNT ON;
    SELECT ActionTypeCode, ActionTypeName FROM ng.ActionType ORDER BY ActionTypeName;
    SELECT RegionCode, RegionName FROM ng.Region ORDER BY RegionName;
END;
GO
