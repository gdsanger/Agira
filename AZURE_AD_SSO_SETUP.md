# Azure AD SSO Configuration

This guide explains how to configure Azure Active Directory (Azure AD) Single Sign-On (SSO) for Agira using MSAL (Microsoft Authentication Library).

---

## Overview

Agira supports Azure AD SSO authentication alongside the traditional username/password login. When enabled, users can log in using their Azure AD credentials, and new users are automatically provisioned with a default role.

### Features

- **Single Sign-On (SSO)** via Azure AD
- **Auto-provisioning** of new users from Azure AD
- **User mapping** by email and Azure AD Object ID
- **Single Logout** support
- **Secure token validation**
- **Configurable default role** for new users
- **Coexistence** with username/password authentication

---

## Prerequisites

1. **Azure AD Tenant** - You need an Azure AD tenant
2. **Admin Access** - You need permissions to register applications in Azure AD
3. **Agira Installation** - A running Agira instance

---

## Azure AD Application Registration

### Step 1: Register the Application

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory** → **App registrations**
3. Click **New registration**
4. Fill in the details:
   - **Name**: `Agira SSO` (or any meaningful name)
   - **Supported account types**: Select based on your needs (typically "Accounts in this organizational directory only")
   - **Redirect URI**: 
     - Platform: `Web`
     - URI: `https://your-agira-domain.com/auth/azuread/callback/`
       - For local development: `http://localhost:8000/auth/azuread/callback/`
5. Click **Register**

### Step 2: Note the Application Details

After registration, note the following values (you'll need them for configuration):

- **Application (client) ID** - Found on the Overview page
- **Directory (tenant) ID** - Found on the Overview page

### Step 3: Create a Client Secret

1. Go to **Certificates & secrets**
2. Click **New client secret**
3. Add a description (e.g., "Agira Production Secret")
4. Select an expiration period
5. Click **Add**
6. **Important**: Copy the secret **Value** immediately - you won't be able to see it again!

### Step 4: Configure API Permissions

1. Go to **API permissions**
2. Click **Add a permission**
3. Select **Microsoft Graph**
4. Select **Delegated permissions**
5. Add the following permissions:
   - `openid` (automatically requested by MSAL)
   - `profile` (automatically requested by MSAL)
   - `email`
   - `User.Read`
   
   **Note**: The `openid` and `profile` scopes are reserved and automatically included by MSAL. 
   Your application code should only request non-reserved scopes like `User.Read` and `email`.
6. Click **Add permissions**
7. (Optional but recommended) Click **Grant admin consent** to pre-approve for all users

### Step 5: Configure Authentication Settings

1. Go to **Authentication**
2. Under **Implicit grant and hybrid flows**, ensure:
   - **ID tokens** is checked (for hybrid flow)
3. Under **Advanced settings**:
   - Set **Allow public client flows** to **No**
4. Click **Save**

---

## Agira Configuration

### Step 1: Update Environment Variables

Add the following to your `.env` file:

```bash
# Azure AD / MSAL Configuration
AZURE_AD_ENABLED=True
AZURE_AD_TENANT_ID=your-tenant-id-here
AZURE_AD_CLIENT_ID=your-client-id-here
AZURE_AD_CLIENT_SECRET=your-client-secret-here
AZURE_AD_REDIRECT_URI=https://your-agira-domain.com/auth/azuread/callback/
AZURE_AD_DEFAULT_ROLE=User
```

**Configuration Parameters:**

- `AZURE_AD_ENABLED`: Set to `True` to enable Azure AD SSO
- `AZURE_AD_TENANT_ID`: The Directory (tenant) ID from Azure AD
- `AZURE_AD_CLIENT_ID`: The Application (client) ID from Azure AD
- `AZURE_AD_CLIENT_SECRET`: The client secret value from Azure AD
- `AZURE_AD_REDIRECT_URI`: Must match exactly with the redirect URI registered in Azure AD
- `AZURE_AD_DEFAULT_ROLE`: Default role for auto-provisioned users (`User`, `Agent`, `Approver`, `ISB`, `Management`)

### Step 2: Apply Database Migration

Run the migration to add the Azure AD field to the User model:

```bash
python manage.py migrate
```

### Step 3: Restart the Application

Restart your Agira application to load the new configuration:

```bash
# For development server
python manage.py runserver

# For production (example with gunicorn)
sudo systemctl restart agira
```

---

## User Experience

### Login Flow

1. Users navigate to the login page
2. They see two options:
   - **Traditional login** with username/password
   - **Login mit Azure AD** button
3. Clicking "Login mit Azure AD":
   - Redirects to Microsoft login page
   - User authenticates with their Azure AD credentials
   - User is redirected back to Agira
   - If the user exists (by email or Azure AD Object ID), they are logged in
   - If the user doesn't exist, a new account is auto-provisioned

### Auto-Provisioning

When a user logs in via Azure AD for the first time:

1. Agira checks if a user with the Azure AD Object ID exists
2. If not, it checks if a user with the email exists
3. If a user with the email exists, it links the Azure AD Object ID to that user
4. If no user exists, it creates a new user with:
   - **Username**: Derived from email (e.g., `john.doe` from `john.doe@example.com`)
   - **Email**: From Azure AD
   - **Name**: From Azure AD profile
   - **Role**: The configured default role (`AZURE_AD_DEFAULT_ROLE`)
   - **Azure AD Object ID**: Linked to prevent duplicates
   - **Active**: `True`

### Logout Flow

When a user who logged in via Azure AD logs out:

- The user is logged out from Agira
- The user is redirected to Azure AD logout endpoint
- This ensures the user is also signed out from Azure AD (single logout)

---

## Security Considerations

### Token Validation

Agira validates Azure AD tokens by checking:

- **Issuer**: Must match the expected Azure AD tenant
- **Audience**: Must match the application client ID
- **Signature**: Tokens must be properly signed (via MSAL)
- **Expiration**: Tokens must not be expired

### CSRF Protection

The Azure AD login flow uses state tokens to prevent CSRF attacks. The state token is:

- Generated randomly for each login attempt
- Stored in the session
- Validated on callback
- Deleted after successful validation

### Secret Management

**Important Security Notes:**

1. **Never commit secrets to version control**
2. Use environment variables or a secret management service
3. Rotate client secrets regularly (at least annually)
4. Use different secrets for different environments (dev/stage/prod)
5. Grant minimum required permissions in Azure AD

### Session Security

Agira uses Django's session management with:

- HTTP-only cookies (JavaScript cannot access)
- Secure cookies (HTTPS only in production)
- CSRF protection on all forms
- Session timeout configuration via Django settings

---

## Troubleshooting

### Common Issues

#### 1. "Azure AD Login ist nicht verfügbar"

**Cause**: Azure AD is not enabled or configuration is incomplete

**Solution**: 
- Check `AZURE_AD_ENABLED=True` in `.env`
- Verify all required settings are present (tenant ID, client ID, client secret, redirect URI)

#### 2. Redirect URI Mismatch

**Error**: AADSTS50011: The reply URL specified in the request does not match...

**Solution**:
- Ensure `AZURE_AD_REDIRECT_URI` in `.env` matches exactly with the redirect URI in Azure AD app registration
- Check protocol (http vs https)
- Check domain and path

#### 3. Invalid Client Secret

**Error**: AADSTS7000215: Invalid client secret provided

**Solution**:
- The client secret may have expired
- Generate a new client secret in Azure AD
- Update `AZURE_AD_CLIENT_SECRET` in `.env`

#### 4. User Creation Fails

**Check logs** for detailed error messages:

```bash
# Django development server logs
tail -f /path/to/agira/logs/django.log

# Or check Docker logs
docker logs agira-app
```

#### 5. Permissions Not Granted

**Error**: User sees permission consent screen

**Solution**:
- Grant admin consent in Azure AD for the required permissions
- Or have users consent individually (if org policy allows)

### Debug Mode

To enable detailed Azure AD authentication logging:

1. Set Django logging level to DEBUG in `settings.py`
2. Check logs for Azure AD authentication events
3. Look for messages starting with "Azure AD" or "MSAL"

**Note**: Never log full tokens or secrets, even in debug mode

---

## Multiple Environments

### Development, Staging, Production

For each environment, register a **separate Azure AD application** with:

- Different redirect URIs
- Different client secrets
- Potentially different permissions

Example configuration:

**Development** (`.env.dev`):
```bash
AZURE_AD_REDIRECT_URI=http://localhost:8000/auth/azuread/callback/
AZURE_AD_CLIENT_ID=dev-client-id
AZURE_AD_CLIENT_SECRET=dev-secret
```

**Production** (`.env.prod`):
```bash
AZURE_AD_REDIRECT_URI=https://agira.example.com/auth/azuread/callback/
AZURE_AD_CLIENT_ID=prod-client-id
AZURE_AD_CLIENT_SECRET=prod-secret
```

---

## Advanced Configuration

### Custom Role Mapping

Currently, all auto-provisioned users receive the same default role. To implement custom role mapping based on Azure AD groups:

1. Request additional permissions in Azure AD (e.g., `Directory.Read.All`)
2. Extend the `get_or_create_user` method in `core/backends/azuread.py`
3. Map Azure AD group memberships to Agira roles

### Token Caching

MSAL includes built-in token caching. For performance optimization in high-traffic scenarios, consider:

1. Using Redis for session storage
2. Implementing token refresh logic
3. Configuring appropriate cache timeouts

---

## Support

For issues or questions:

1. Check the application logs
2. Review Azure AD sign-in logs (Azure Portal → Azure AD → Sign-in logs)
3. Consult Microsoft's [MSAL Python documentation](https://github.com/AzureAD/microsoft-authentication-library-for-python)
4. Open an issue on the Agira repository

---

## References

- [Microsoft Authentication Library (MSAL) for Python](https://github.com/AzureAD/microsoft-authentication-library-for-python)
- [Azure AD Documentation](https://docs.microsoft.com/en-us/azure/active-directory/)
- [OAuth 2.0 and OpenID Connect](https://docs.microsoft.com/en-us/azure/active-directory/develop/active-directory-v2-protocols)
