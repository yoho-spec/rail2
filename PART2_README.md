# Part 2: User Account Login (MTProto / Telethon)

## Overview
Part 2 implements the Telethon-based login system that allows users to connect their Telegram accounts to the bot. This is required for advanced features like live forwarding, private chat archiving, and history search.

## Architecture

### Files Added/Modified

#### `auth/session_manager.py`
- **SessionManager class**: Manages Telethon client lifecycle per user
  - `get_client(user_id)`: Retrieve active client from encrypted session
  - `save_session(user_id, client)`: Encrypt and store session in MongoDB
  - `delete_session(user_id)`: Logout (delete session)
  - `is_logged_in(user_id)`: Check if user has active session

**Key Detail**: Sessions are encrypted with `SESSION_ENCRYPTION_KEY` before storage in MongoDB. This prevents exposure if the DB is compromised.

#### `auth/login_flow.py`
- **start_login(user_id, phone_number)**: Initiate login, send OTP
- **verify_otp(user_id, otp_code)**: Verify OTP, handle 2FA if needed
- **verify_2fa(user_id, password)**: Complete 2FA verification
- **_temp_clients dict**: Stores temporary Telethon clients during login (in-memory)

**Flow**:
1. User sends `/login`
2. Bot asks for phone number
3. Bot sends OTP to that phone
4. User enters OTP code
5. If 2FA enabled, bot asks for password
6. Session saved to MongoDB, user logged in

#### `handlers/auth.py`
- **login_conversation**: ConversationHandler managing the multi-step login flow
- **logout_handler**: Delete session and log user out
- **mychats_handler**: Fetch user's chats via Telethon, display list, save to DB

#### `database/schemas.py`
- MongoDB collection schemas for:
  - `users`: Stores user data, encrypted session, chat list
  - `archive_jobs`: Forwarding jobs (Part 3)
  - `duplicate_logs`: Duplicate detection logs (Part 4)
  - `premium_users`: Premium user list
  - `admin_logs`: Admin action audit trail
- `create_indexes()`: Creates performance indexes

#### `database/mongodb.py`
- Updated to call `create_indexes()` on init

#### `main.py`
- Added `login_conversation` handler
- Added `/logout` and `/mychats` command handlers
- Updated bot commands menu

## How It Works

### Login Flow (Step-by-Step)

```
User: /login
Bot: "Enter your phone number (+1234567890):"
User: +1234567890
Bot: "OTP sent to +1234567890. Reply with /verify <code>"
[User receives OTP on Telegram]
User: 1234 (the OTP code)
Bot: "✅ Logged in as John Doe. Use /mychats to see your chats."
```

### Session Storage

```python
# In MongoDB users collection:
{
  "_id": 123456789,  # user_id
  "telegram_name": "John Doe",
  "logged_in": true,
  "telethon_session": "gANVDQAAAHNvbWVfZW5jcnlwdGVkX3N0cmluZ...",  # Encrypted
  "chats": [
    {"id": -1001234567890, "name": "My Channel", "type": "Channel", ...},
    {"id": -1001234567891, "name": "My Group", "type": "Group", ...},
    {"id": 987654321, "name": "John Smith", "type": "Private", ...}
  ]
}
```

### /mychats Command

When user runs `/mychats`:
1. Bot retrieves encrypted session from DB
2. Decrypts and creates Telethon client
3. Fetches all dialogs (chats) via `client.get_dialogs()`
4. Saves chat list to DB for later reference
5. Displays formatted list to user

```
📋 Your Chats:

1. My Channel (Channel) - ID: `-1001234567890`
2. My Group (Group) - ID: `-1001234567891`
3. John Smith (Private) - ID: `987654321`

💡 Use /setdest to select destination chats for archiving.
```

## Security Considerations

### Session Encryption
- Sessions are encrypted with `SESSION_ENCRYPTION_KEY` (32-byte hex from environment)
- Only the encrypted string is stored in MongoDB
- If DB is compromised, sessions cannot be decrypted without the key

### Rate Limiting
- Telethon has built-in rate limiting to avoid Telegram bans
- OTP timeout: 5 minutes (configurable in `LOGIN_TIMEOUT`)
- Temp clients are cleaned up after login or timeout

### 2FA Support
- If user has 2FA enabled, bot asks for password after OTP
- Password is never stored, only used for one-time verification

### Multi-User Sessions
- Each user has their own encrypted session
- Multiple users can be logged in simultaneously
- Sessions are isolated per user_id

## Environment Variables Required

```bash
# Existing (Part 1)
BOT_TOKEN=...
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
MONGODB_URI=...
REDIS_URL=...
SESSION_ENCRYPTION_KEY=...  # 32-byte hex, e.g., openssl rand -hex 32

# Optional
ADMIN_USER_IDS=123456789,987654321
REQUIRED_CHANNELS=@mychannel,@otherchannel
```

## Testing Part 2

### Local Testing
```bash
# 1. Set environment variables
export BOT_TOKEN="your_token"
export TELEGRAM_API_ID=123456
export TELEGRAM_API_HASH="abc123..."
export MONGODB_URI="mongodb+srv://..."
export REDIS_URL="rediss://..."
export SESSION_ENCRYPTION_KEY=$(openssl rand -hex 32)

# 2. Run bot
python main.py

# 3. In Telegram, message your bot:
/start
/login
# Follow prompts
/mychats
```

### What to Verify
- [ ] `/login` starts conversation
- [ ] OTP is sent to your phone
- [ ] Entering OTP logs you in
- [ ] `/mychats` lists your chats
- [ ] `/logout` disconnects your account
- [ ] Session is encrypted in MongoDB
- [ ] 2FA works if you have it enabled

## Known Limitations

1. **Temp Clients in Memory**: Currently stores temp clients in a module-level dict. For production with many concurrent logins, use Redis or a proper session store.

2. **50 Chat Limit**: `/mychats` currently limits to 50 chats. Can be increased or paginated.

3. **No Session Expiry**: Sessions don't auto-expire. Users must manually `/logout` or admin can delete from DB.

4. **Single API Credentials**: All users use the same `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`. This is standard but means Telegram can rate-limit the entire bot if one user abuses it.

## Next Steps (Part 3)

Part 3 will implement the **Archiver Core** using these logged-in sessions:
- Set source chats (groups, channels, topics, private chats)
- Set target/destination chats
- Forward messages with original sender header
- Live forwarding toggle
- Handle edited messages
- Store forwarded content in admin-only topics

## Debugging

### Session Not Restoring
```python
# Check if session is encrypted properly
user_doc = await db.users.find_one({"_id": user_id})
print(user_doc.get("telethon_session"))  # Should be encrypted string
```

### OTP Timeout
- User has 5 minutes to enter OTP
- If timeout, user must `/login` again

### 2FA Issues
- Ensure password is correct
- If locked out, use Telegram app to reset 2FA

## Code Quality Notes

- All async functions properly await
- Error handling with try/except and logging
- Encryption/decryption wrapped in try/except
- Session cleanup on success or timeout
- Proper use of ConversationHandler for multi-step flow

---

**Status**: ✅ Part 2 Complete  
**Next**: Part 3 - Archiver Core (Forwarding Engine)

