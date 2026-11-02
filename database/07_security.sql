/*
    Step 07: the database role for the app's login.

    The role can run the app procedures and read the rpt and pub views, and nothing else: no table can be read
    or written directly, and the audit trail is reachable only through the procedures. Setup procedures
    (bootstrap, history import) are not granted.

    The ng synonyms read NorthGridOps. Cross-database ownership chaining is off, so a production login also needs
    a NorthGridOps user with SELECT on ops.Circuit, ops.Customer, ops.Incident, ops.ImprovementAction, ref.Region
    and ref.ActionType. That grant is a change to NorthGridOps and is left to its owner (docs/03-architecture.md).
*/
IF DATABASE_PRINCIPAL_ID(N'portal_app') IS NULL
    CREATE ROLE portal_app;
GO

DECLARE @Grants nvarchar(max) = (
    SELECT STRING_AGG(CAST(N'GRANT EXECUTE ON app.' + QUOTENAME(name) + N' TO portal_app;' AS nvarchar(max)), NCHAR(10))
    FROM sys.procedures
    WHERE SCHEMA_NAME(schema_id) = N'app'
      AND name LIKE N'usp[_]%'
      AND name NOT IN (N'usp_BootstrapAdmin', N'usp_ImportHistory', N'usp_SetContext', N'usp_ClearContext',
                       N'usp_CheckRoleRegion'));
EXEC (@Grants);

GRANT SELECT ON SCHEMA::rpt TO portal_app;
GRANT SELECT ON SCHEMA::pub TO portal_app;
GO
