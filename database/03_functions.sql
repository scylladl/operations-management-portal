/*
    Step 03: the clock, working days, the evidence window, visibility (R10) and allowed transitions.
*/
CREATE OR ALTER FUNCTION app.fn_Now()
RETURNS datetime2(0)
AS
BEGIN
    RETURN CASE WHEN (SELECT SettingValue FROM app.Setting WHERE SettingCode = 'DemoClock') = 1
                     AND SESSION_CONTEXT(N'portal.clock') IS NOT NULL
                THEN CAST(SESSION_CONTEXT(N'portal.clock') AS datetime2(0))
                ELSE CAST(SYSDATETIME() AS datetime2(0)) END;
END;
GO

-- Monday-to-Friday days after @From up to and including @To (no holiday calendar in version 1).
-- 1900-01-01 was a Monday, so the day number modulo 7 is 0-4 on working days, whatever DATEFIRST is.
CREATE OR ALTER FUNCTION app.fn_WorkingDays (@From date, @To date)
RETURNS TABLE
AS RETURN
    SELECT COUNT(*) AS WorkingDays
    FROM GENERATE_SERIES(1, DATEDIFF(day, @From, @To), 1) AS g
    WHERE DATEDIFF(day, '19000101', DATEADD(day, g.value, @From)) % 7 < 5;
GO

-- R2: the 90 days that end with the latest incident in the NorthGrid extraction, not with today, because the
-- portal can only show what the last extraction loaded. Cancelled tickets and duplicates are not evidence.
CREATE OR ALTER VIEW app.vw_EvidenceWindow
AS
    SELECT DATEADD(day, -89, w.WindowEnd) AS WindowStart, w.WindowEnd
    FROM (SELECT CAST(MAX(OpenedAt) AS date) AS WindowEnd FROM ng.Incident) AS w;
GO

CREATE OR ALTER VIEW app.vw_EvidenceIncident
AS
    SELECT i.TicketId, i.CircuitId, i.OpenedAt, i.PriorityCode, i.RootCauseCode, i.ResponsibleTeam, i.Status
    FROM ng.Incident AS i
    CROSS JOIN app.vw_EvidenceWindow AS w
    WHERE i.OpenedAt >= w.WindowStart
      AND i.OpenedAt < DATEADD(day, 1, w.WindowEnd)
      AND i.IsCancelled = 0
      AND i.DuplicateOfTicketId IS NULL;
GO

-- R10: requesters see their own requests and the open actions of their region; approvers and field coordinators
-- see their region; administrators see everything. A draft is seen only by its requester.
CREATE OR ALTER FUNCTION app.fn_VisibleActions (@ActorUserId int)
RETURNS TABLE
AS RETURN
    SELECT a.ActionId
    FROM app.Action AS a
    JOIN app.UserAccount AS u ON u.UserId = @ActorUserId AND u.IsActive = 1
    JOIN ref.Status AS s ON s.StatusCode = a.Status
    WHERE a.RequesterId = @ActorUserId
       OR (a.Status <> 'Draft'
           AND (u.RoleCode = 'ADM'
                OR (u.RoleCode IN ('APR', 'FLD') AND a.RegionCode = u.RegionCode)
                OR (u.RoleCode = 'REQ' AND a.RegionCode = u.RegionCode AND s.IsOpen = 1)));
GO

-- What the actor may do on the action now. app.usp_Transition refuses anything not returned here, and the app
-- shows a button for each row, so the screen and the database apply the same rules.
CREATE OR ALTER FUNCTION app.fn_AllowedTransitions (@ActorUserId int, @ActionId int)
RETURNS TABLE
AS RETURN
    SELECT t.TransitionCode, t.ActionLabel, t.ToStatus, t.RequiresReason
    FROM app.Action AS a
    JOIN ref.Transition AS t ON t.FromStatus = a.Status
    JOIN app.UserAccount AS u ON u.UserId = @ActorUserId AND u.IsActive = 1 AND u.RoleCode = t.RoleCode
    WHERE a.ActionId = @ActionId
      AND (u.RoleCode = 'ADM' OR u.RegionCode = a.RegionCode)                                  -- R3, R6
      AND (t.MustBeOwner = 0 OR a.RequesterId = @ActorUserId)
      AND (t.MustNotBeOwner = 0 OR a.RequesterId IS NULL OR a.RequesterId <> @ActorUserId)     -- R3
      AND (a.IsHistorical = 0 OR t.TransitionCode = 'COMPLETE');                                 -- Q6, R14
GO

CREATE OR ALTER PROCEDURE app.usp_SetContext
    @ActorUserId int, @EventType varchar(12), @Reason nvarchar(1000), @Now datetime2(0)
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_set_session_context N'portal.actor', @ActorUserId;
    EXEC sp_set_session_context N'portal.event', @EventType;
    EXEC sp_set_session_context N'portal.reason', @Reason;
    EXEC sp_set_session_context N'portal.now', @Now;
END;
GO

CREATE OR ALTER PROCEDURE app.usp_ClearContext
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_set_session_context N'portal.actor', NULL;
    EXEC sp_set_session_context N'portal.event', NULL;
    EXEC sp_set_session_context N'portal.reason', NULL;
    EXEC sp_set_session_context N'portal.now', NULL;
END;
GO
