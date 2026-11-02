/*
    Independent check of app.usp_GetIndicators (AC-07), all regions.

    Written without rpt.vw_ActionCycle or app.fn_WorkingDays: working days come from a calendar built here and
    DATEPART(weekday), and the cycle is read straight from the audit trail. Run it on the portal database;
    tests/test_indicators.py compares its four result sets with the procedure's.
*/
SET NOCOUNT ON;

DECLARE @Today date = CAST(app.fn_Now() AS date);

WITH Calendar AS (
    SELECT CAST('2025-01-01' AS date) AS d
    UNION ALL
    SELECT DATEADD(day, 1, d) FROM Calendar WHERE d < DATEADD(day, 400, @Today)
)
SELECT d, IIF((DATEPART(weekday, d) + @@DATEFIRST - 2) % 7 < 5, 1, 0) AS IsWorkingDay
INTO #Calendar
FROM Calendar
OPTION (MAXRECURSION 0);

SELECT a.ActionId, a.RegionCode, a.ActionTypeCode, a.Status, a.LastSubmittedAt, a.CompletionDate,
       (SELECT MIN(EventAt) FROM audit.ActionEvent
        WHERE ActionId = a.ActionId AND EventType = 'SUBMIT' AND FieldName = 'Status') AS FirstSubmittedAt,
       (SELECT MIN(EventAt) FROM audit.ActionEvent
        WHERE ActionId = a.ActionId AND NewValue IN ('Approved', 'Rejected') AND FieldName = 'Status'
          AND OldValue = 'Submitted') AS DecidedAt,
       (SELECT MIN(NewValue) FROM audit.ActionEvent
        WHERE ActionId = a.ActionId AND NewValue IN ('Approved', 'Rejected') AND FieldName = 'Status'
          AND OldValue = 'Submitted') AS Decision,
       (SELECT COUNT(*) FROM audit.ActionEvent
        WHERE ActionId = a.ActionId AND OldValue = 'Submitted' AND NewValue = 'Returned' AND FieldName = 'Status') AS TimesReturned
INTO #Cycle
FROM app.Action AS a
WHERE a.IsHistorical = 0 AND a.Status <> 'Draft';

SELECT c.RegionCode,
       CASE WHEN w.Days <= 2 THEN '0-2' WHEN w.Days <= 5 THEN '3-5' ELSE 'Over 5' END AS WaitingBucket,
       COUNT(*) AS Actions
FROM #Cycle AS c
CROSS APPLY (SELECT SUM(IsWorkingDay) AS Days FROM #Calendar
             WHERE d > CAST(c.LastSubmittedAt AS date) AND d <= @Today) AS w0
CROSS APPLY (SELECT COALESCE(w0.Days, 0) AS Days) AS w
WHERE c.Status = 'Submitted'
GROUP BY c.RegionCode, CASE WHEN w.Days <= 2 THEN '0-2' WHEN w.Days <= 5 THEN '3-5' ELSE 'Over 5' END
ORDER BY c.RegionCode, WaitingBucket;

SELECT c.RegionCode,
       COUNT(*) AS Decided,
       SUM(IIF(c.Decision = 'Approved', 1, 0)) AS Approved,
       SUM(IIF(c.Decision = 'Rejected', 1, 0)) AS Rejected,
       SUM(IIF(c.TimesReturned > 0, 1, 0)) AS ReturnedAtLeastOnce,
       CAST(1.0 * SUM(IIF(c.TimesReturned > 0, 1, 0)) / COUNT(*) AS decimal(5, 3)) AS ReturnRate,
       CAST(AVG(1.0 * COALESCE(w.Days, 0)) AS decimal(9, 1)) AS AvgWorkingDaysToDecision
FROM #Cycle AS c
OUTER APPLY (SELECT SUM(IsWorkingDay) AS Days FROM #Calendar
             WHERE d > CAST(c.FirstSubmittedAt AS date) AND d <= CAST(c.DecidedAt AS date)) AS w
WHERE c.Decision IS NOT NULL
GROUP BY c.RegionCode
ORDER BY c.RegionCode;

SELECT RegionCode, COUNT(*) AS Completed,
       CAST(AVG(1.0 * DATEDIFF(day, CAST(DecidedAt AS date), CompletionDate)) AS decimal(9, 1)) AS AvgDaysToComplete
FROM #Cycle
WHERE Status IN ('Completed', 'Verified') AND Decision = 'Approved'
GROUP BY RegionCode
ORDER BY RegionCode;

SELECT RegionCode, ActionTypeCode, Status, COUNT(*) AS Actions
FROM #Cycle
GROUP BY RegionCode, ActionTypeCode, Status
ORDER BY RegionCode, ActionTypeCode, Status;
