/*
    Step 05: accounts (R11). The app hashes passwords (Argon2id) before calling; the database never sees one in clear.
*/
CREATE OR ALTER PROCEDURE app.usp_BootstrapAdmin
    @Login varchar(50), @DisplayName nvarchar(100), @PasswordHash varchar(200)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @Now datetime2(0) = app.fn_Now();
    IF EXISTS (SELECT 1 FROM app.UserAccount WHERE RoleCode = 'ADM')
        THROW 50001, 'An administrator already exists; accounts are created by administrators.', 1;
    EXEC app.usp_SetContext NULL, 'BOOTSTRAP', NULL, @Now;
    BEGIN TRY
        INSERT app.UserAccount (Login, DisplayName, RoleCode, RegionCode, PasswordHash, IsActive, CreatedAt)
        VALUES (@Login, @DisplayName, 'ADM', NULL, @PasswordHash, 1, @Now);
    END TRY
    BEGIN CATCH
        EXEC app.usp_ClearContext;
        THROW;
    END CATCH;
    EXEC app.usp_ClearContext;
    SELECT CAST(SCOPE_IDENTITY() AS int) AS UserId;
END;
GO

-- Sign-up: an inactive account without a role until an administrator activates it
CREATE OR ALTER PROCEDURE app.usp_RequestAccount
    @Login varchar(50), @DisplayName nvarchar(100), @PasswordHash varchar(200)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @Now datetime2(0) = app.fn_Now();
    SET @Login = NULLIF(TRIM(@Login), '');
    SET @DisplayName = NULLIF(TRIM(@DisplayName), N'');
    IF @Login IS NULL OR @DisplayName IS NULL
        THROW 50002, 'Login and name are required.', 1;
    IF EXISTS (SELECT 1 FROM app.UserAccount WHERE Login = @Login)
        THROW 50002, 'This login is already taken.', 1;
    EXEC app.usp_SetContext NULL, 'SIGNUP', NULL, @Now;
    BEGIN TRY
        INSERT app.UserAccount (Login, DisplayName, RoleCode, RegionCode, PasswordHash, IsActive, CreatedAt)
        VALUES (@Login, @DisplayName, NULL, NULL, @PasswordHash, 0, @Now);
    END TRY
    BEGIN CATCH
        EXEC app.usp_ClearContext;
        THROW;
    END CATCH;
    EXEC app.usp_ClearContext;
    SELECT CAST(SCOPE_IDENTITY() AS int) AS UserId;
END;
GO

CREATE OR ALTER PROCEDURE app.usp_CheckRoleRegion
    @RoleCode char(3), @RegionCode char(3)
AS
BEGIN
    IF @RoleCode NOT IN ('REQ', 'APR', 'FLD', 'ADM')
        THROW 50002, 'Unknown role.', 1;
    IF @RoleCode = 'ADM' AND @RegionCode IS NOT NULL
        THROW 50002, 'Administrators are not tied to a region.', 1;
    IF @RoleCode <> 'ADM' AND NOT EXISTS (SELECT 1 FROM ng.Region WHERE RegionCode = @RegionCode)
        THROW 50002, 'Requesters, approvers and field coordinators need a region.', 1;
END;
GO

CREATE OR ALTER PROCEDURE app.usp_CreateAccount
    @ActorUserId int, @Login varchar(50), @DisplayName nvarchar(100), @RoleCode char(3), @RegionCode char(3),
    @PasswordHash varchar(200)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @Now datetime2(0) = app.fn_Now();
    IF NOT EXISTS (SELECT 1 FROM app.UserAccount WHERE UserId = @ActorUserId AND IsActive = 1 AND RoleCode = 'ADM')
        THROW 50001, 'Only administrators manage accounts.', 1;
    SET @Login = NULLIF(TRIM(@Login), '');
    SET @DisplayName = NULLIF(TRIM(@DisplayName), N'');
    IF @Login IS NULL OR @DisplayName IS NULL
        THROW 50002, 'Login and name are required.', 1;
    IF EXISTS (SELECT 1 FROM app.UserAccount WHERE Login = @Login)
        THROW 50002, 'This login is already taken.', 1;
    EXEC app.usp_CheckRoleRegion @RoleCode, @RegionCode;

    EXEC app.usp_SetContext @ActorUserId, 'CREATE', NULL, @Now;
    BEGIN TRY
        INSERT app.UserAccount (Login, DisplayName, RoleCode, RegionCode, PasswordHash, IsActive, CreatedAt)
        VALUES (@Login, @DisplayName, @RoleCode, @RegionCode, @PasswordHash, 1, @Now);
    END TRY
    BEGIN CATCH
        EXEC app.usp_ClearContext;
        THROW;
    END CATCH;
    EXEC app.usp_ClearContext;
    SELECT CAST(SCOPE_IDENTITY() AS int) AS UserId;
END;
GO

-- Role, region and activation. Activating a sign-up request is this call with a role and IsActive = 1.
CREATE OR ALTER PROCEDURE app.usp_UpdateAccount
    @ActorUserId int, @UserId int, @RoleCode char(3), @RegionCode char(3), @IsActive bit, @RowVer binary(8)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @Now datetime2(0) = app.fn_Now();
    IF NOT EXISTS (SELECT 1 FROM app.UserAccount WHERE UserId = @ActorUserId AND IsActive = 1 AND RoleCode = 'ADM')
        THROW 50001, 'Only administrators manage accounts.', 1;
    EXEC app.usp_CheckRoleRegion @RoleCode, @RegionCode;

    EXEC app.usp_SetContext @ActorUserId, 'UPDATE', NULL, @Now;
    BEGIN TRY
        UPDATE app.UserAccount
        SET RoleCode = @RoleCode, RegionCode = @RegionCode, IsActive = @IsActive
        WHERE UserId = @UserId AND RowVer = @RowVer;
        IF @@ROWCOUNT = 0
            THROW 50003, 'This account changed since you opened it, or it does not exist.', 1;
    END TRY
    BEGIN CATCH
        EXEC app.usp_ClearContext;
        THROW;
    END CATCH;
    EXEC app.usp_ClearContext;
END;
GO

-- A user changes their own password; an administrator resets anyone's
CREATE OR ALTER PROCEDURE app.usp_SetPassword
    @ActorUserId int, @UserId int, @PasswordHash varchar(200)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    DECLARE @Now datetime2(0) = app.fn_Now();
    IF NOT EXISTS (SELECT 1 FROM app.UserAccount
                   WHERE UserId = @ActorUserId AND IsActive = 1 AND (RoleCode = 'ADM' OR @ActorUserId = @UserId))
        THROW 50001, 'You cannot change this password.', 1;

    EXEC app.usp_SetContext @ActorUserId, 'PASSWORD', NULL, @Now;
    BEGIN TRY
        UPDATE app.UserAccount SET PasswordHash = @PasswordHash WHERE UserId = @UserId;
    END TRY
    BEGIN CATCH
        EXEC app.usp_ClearContext;
        THROW;
    END CATCH;
    EXEC app.usp_ClearContext;
END;
GO

CREATE OR ALTER PROCEDURE app.usp_GetSignIn
    @Login varchar(50) = NULL, @UserId int = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SELECT UserId, Login, DisplayName, RoleCode, RegionCode, IsActive, PasswordHash
    FROM app.UserAccount
    WHERE Login = @Login OR UserId = @UserId;
END;
GO

CREATE OR ALTER PROCEDURE app.usp_GetAccount
    @UserId int
AS
BEGIN
    SET NOCOUNT ON;
    SELECT u.UserId, u.Login, u.DisplayName, u.RoleCode, ro.RoleName, u.RegionCode, re.RegionName, u.IsActive, u.RowVer
    FROM app.UserAccount AS u
    LEFT JOIN ref.Role AS ro ON ro.RoleCode = u.RoleCode
    LEFT JOIN ng.Region AS re ON re.RegionCode = u.RegionCode
    WHERE u.UserId = @UserId;
END;
GO

CREATE OR ALTER PROCEDURE app.usp_ListAccounts
    @ActorUserId int
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM app.UserAccount WHERE UserId = @ActorUserId AND IsActive = 1 AND RoleCode = 'ADM')
        THROW 50001, 'Only administrators manage accounts.', 1;
    SELECT u.UserId, u.Login, u.DisplayName, u.RoleCode, ro.RoleName, u.RegionCode, u.IsActive,
           CASE WHEN u.RoleCode IS NULL THEN 'Pending' WHEN u.IsActive = 1 THEN 'Active' ELSE 'Disabled' END AS AccountStatus,
           u.CreatedAt, u.RowVer
    FROM app.UserAccount AS u
    LEFT JOIN ref.Role AS ro ON ro.RoleCode = u.RoleCode
    ORDER BY CASE WHEN u.RoleCode IS NULL THEN 0 ELSE 1 END, u.RoleCode, u.RegionCode, u.DisplayName;
END;
GO
