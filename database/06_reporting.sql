/*
    Step 06: follow-up indicators (requirements section 7) and the export for the NorthGrid report (Q7).

    Indicator definitions. Historical actions are left out: they have no submissions or decisions.
      Waiting for decision  Submitted actions by working days since the last submission: 0-2, 3-5, over 5
      Time to decision      working days from the first submission to the approval or rejection
      Return rate           decided actions returned at least once / decided actions
      Time to complete      calendar days from the approval to the completion date (Completed and Verified)
    Working days are Monday to Friday after the start date up to the end date; there is no holiday calendar.
*/
CREATE OR ALTER VIEW rpt.vw_ActionCycle
AS
    SELECT  a.ActionId, a.RegionCode, a.ActionTypeCode, a.Status,
            sub.FirstSubmittedAt, a.LastSubmittedAt, dec.DecidedAt, dec.Decision,
            COALESCE(ret.TimesReturned, 0) AS TimesReturned,
            IIF(dec.DecidedAt IS NULL, NULL, toDecision.WorkingDays) AS WorkingDaysToDecision,
            a.CompletionDate,
            IIF(a.Status IN ('Completed', 'Verified') AND dec.Decision = 'Approved',
                DATEDIFF(day, CAST(dec.DecidedAt AS date), a.CompletionDate), NULL) AS DaysToComplete,
            IIF(a.Status = 'Submitted', waiting.WorkingDays, NULL) AS WaitingWorkingDays,
            CASE WHEN a.Status <> 'Submitted' THEN NULL
                 WHEN waiting.WorkingDays <= 2 THEN '0-2'
                 WHEN waiting.WorkingDays <= 5 THEN '3-5'
                 ELSE 'Over 5' END AS WaitingBucket
    FROM app.Action AS a
    OUTER APPLY (SELECT MIN(e.EventAt) AS FirstSubmittedAt FROM audit.ActionEvent AS e
                 WHERE e.ActionId = a.ActionId AND e.EventType = 'SUBMIT' AND e.FieldName = 'Status') AS sub
    OUTER APPLY (SELECT TOP (1) e.EventAt AS DecidedAt, e.NewValue AS Decision FROM audit.ActionEvent AS e
                 WHERE e.ActionId = a.ActionId AND e.EventType IN ('APPROVE', 'REJECT') AND e.FieldName = 'Status'
                 ORDER BY e.EventId) AS dec
    OUTER APPLY (SELECT COUNT(*) AS TimesReturned FROM audit.ActionEvent AS e
                 WHERE e.ActionId = a.ActionId AND e.EventType = 'RETURN' AND e.FieldName = 'Status') AS ret
    OUTER APPLY app.fn_WorkingDays(CAST(sub.FirstSubmittedAt AS date), CAST(dec.DecidedAt AS date)) AS toDecision
    OUTER APPLY app.fn_WorkingDays(CAST(a.LastSubmittedAt AS date), CAST(app.fn_Now() AS date)) AS waiting
    WHERE a.IsHistorical = 0 AND a.Status <> 'Draft';
GO

-- Approvers see their region, administrators every region
CREATE OR ALTER PROCEDURE app.usp_GetIndicators
    @ActorUserId int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Role char(3), @Region char(3);
    SELECT @Role = RoleCode, @Region = RegionCode FROM app.UserAccount WHERE UserId = @ActorUserId AND IsActive = 1;
    IF @Role IS NULL OR @Role NOT IN ('APR', 'ADM')
        THROW 50001, 'Indicators are for approvers and administrators.', 1;

    SELECT c.* INTO #Cycle FROM rpt.vw_ActionCycle AS c WHERE @Role = 'ADM' OR c.RegionCode = @Region;

    SELECT RegionCode, WaitingBucket, COUNT(*) AS Actions
    FROM #Cycle WHERE Status = 'Submitted'
    GROUP BY RegionCode, WaitingBucket
    ORDER BY RegionCode, WaitingBucket;

    SELECT RegionCode,
           COUNT(*) AS Decided,
           SUM(IIF(Decision = 'Approved', 1, 0)) AS Approved,
           SUM(IIF(Decision = 'Rejected', 1, 0)) AS Rejected,
           SUM(IIF(TimesReturned > 0, 1, 0)) AS ReturnedAtLeastOnce,
           CAST(1.0 * SUM(IIF(TimesReturned > 0, 1, 0)) / COUNT(*) AS decimal(5, 3)) AS ReturnRate,
           CAST(AVG(1.0 * WorkingDaysToDecision) AS decimal(9, 1)) AS AvgWorkingDaysToDecision
    FROM #Cycle WHERE Decision IS NOT NULL
    GROUP BY RegionCode
    ORDER BY RegionCode;

    SELECT RegionCode, COUNT(*) AS Completed, CAST(AVG(1.0 * DaysToComplete) AS decimal(9, 1)) AS AvgDaysToComplete
    FROM #Cycle WHERE DaysToComplete IS NOT NULL
    GROUP BY RegionCode
    ORDER BY RegionCode;

    SELECT RegionCode, ActionTypeCode, Status, COUNT(*) AS Actions
    FROM #Cycle
    GROUP BY RegionCode, ActionTypeCode, Status
    ORDER BY RegionCode, ActionTypeCode, Status;
END;
GO

-- Q7: actions in the six columns of the NorthGrid improvement_actions.csv export. Only work that started is
-- exported, because the NorthGrid table needs a start date; a request never approved or cancelled before the
-- start never became an improvement action there.
CREATE OR ALTER VIEW pub.vw_ImprovementActionExport
AS
    SELECT ActionId, CircuitId, ActionTypeCode, StartDate, CompletionDate,
           CAST(CASE Status WHEN 'InProgress' THEN 'In progress'
                            WHEN 'Verified' THEN 'Completed'
                            ELSE Status END AS varchar(12)) AS Status
    FROM app.Action
    WHERE StartDate IS NOT NULL AND Status IN ('InProgress', 'Completed', 'Verified', 'Cancelled');
GO
